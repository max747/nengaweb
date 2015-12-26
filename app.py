# coding: utf-8

from __future__ import absolute_import, unicode_literals, division, print_function

from collections import MutableMapping as DictMixin
import csv
from datetime import datetime
import functools
import io
import os

from bottle import (
        get,
        post,
        run,
        static_file,
        url,
        jinja2_view,
        redirect,
        request,
    )
from six import StringIO
from sqlalchemy import (
        create_engine,
        Column,
        DateTime,
        ForeignKey,
        Integer,
        String,
    )
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import (
        joinedload,
        sessionmaker,
        relationship,
    )


###################### MODELS

basedir = os.path.dirname(os.path.abspath(__file__))

db_url = "sqlite:///{}".format(os.path.join(basedir, "nenga.sqlite3"))
engine = create_engine(db_url, echo=True, encoding=str("utf-8"))
Session = sessionmaker(bind=engine)
session = Session()
Base = declarative_base()


######
#
# スキーマ構造
#   - Person           ... 人に対応。一度作られたら変化しない。
#   - Address          ... 住所に対応。引っ越しなどで変化しうる。Person と 1-N の関係。
#   - AvailableAddress ... 現在有効な Address を指す。Person と 1-1 の関係。
#   - Nenga            ... 年賀状に対応。毎年作られる。出さない場合も作られる。
#                          出さなかった、来なかった、のステータスも記録するため。
#   - Year             ... 年に対応。サイドメニュー表示とデータロックに使う。
#

class Person(Base):
    __tablename__ = "people"

    id = Column(Integer, primary_key=True)
    family_name = Column(String(20), nullable=False)
    given_name = Column(String(20), nullable=False)
    # 0: アクティブ, 1: 非表示
    # 今後、確実に年賀状を出さないであろう人には 1 を設定。
    disabled = Column(Integer, nullable=False)
    last_update = Column(DateTime, nullable=False, default=datetime.now(), onupdate=datetime.now())
    addresses = relationship("Address", back_populates="person")
    available = relationship("AvailableAddress", back_populates="person", uselist=False)


class Address(Base):
    __tablename__ = "addresses"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=False)
    family_name = Column(String(20), nullable=False)
    given_name = Column(String(20), nullable=False)
    joint_name1 = Column(String(20), nullable=True)
    joint_name2 = Column(String(20), nullable=True)
    zipcode = Column(String(7), nullable=False)
    address1 = Column(String(100), nullable=False)
    address2 = Column(String(100), nullable=True)
    last_update = Column(DateTime, nullable=False, default=datetime.now(), onupdate=datetime.now())
    person = relationship("Person", back_populates="addresses")
    available = relationship("AvailableAddress", back_populates="address", uselist=False)


class AvailableAddress(Base):
    __tablename__ = "available_addresses"

    person_id = Column(Integer, ForeignKey("people.id"), primary_key=True)
    address_id = Column(Integer, ForeignKey("addresses.id"), nullable=False)
    last_update = Column(DateTime, nullable=False, default=datetime.now(), onupdate=datetime.now())
    person = relationship("Person", back_populates="available", uselist=False)
    address = relationship("Address", back_populates="available", uselist=False)


class Nenga(Base):
    __tablename__ = "nenga"

    id = Column(Integer, primary_key=True)
    address_id = Column(Integer, ForeignKey("addresses.id"), nullable=False)
    year = Column(Integer, ForeignKey("years.year"), nullable=False)
    # 0: 出していない, 1: 出した, 2: 返事で出した
    printing = Column(Integer, nullable=False)
    # 0: 受け取っていない, 1: 受け取った, 2: 返事で受け取った
    received = Column(Integer, nullable=False)
    # 0: 喪中ではない, 1: 喪中
    mourning = Column(Integer, nullable=False)
    last_update = Column(DateTime, nullable=False, default=datetime.now(), onupdate=datetime.now())
    address = relationship("Address", backref="nengas")


class Year(Base):
    __tablename__ = "years"

    year = Column(Integer, primary_key=True)
    # 0: 編集可, 1: 編集不可
    lock = Column(Integer, nullable=False)
    nenga = relationship("Nenga")


def initdb(args):
    if args.drop_create:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def init_nextyear(args):
    nextyear = datetime.now().year + 1
    if session.query(Year).filter_by(year=nextyear).count() != 0:
        raise ValueError("nextyear {}'s data are already initialized".format(nextyear))

    y = Year()
    y.year = nextyear
    y.lock = 0
    session.add(y)
    session.commit()

    candidates = session.query(Address).join(Address.available).order_by(Address.id).all()
    for candidate in candidates:
        n = Nenga()
        n.address_id = candidate.id
        n.year = nextyear
        # 基本的に出すための住所録なので、デフォルトは "送付する" であるべき
        n.printing = 1
        n.received = 0
        n.mourning = 0
        session.add(n)
    session.commit()


###################### VIEWS

def code_to_value(code, dic):
    c = int(code)
    if c in dic:
        return dic[c]
    return code


def if_not_none(value, not_none_symbol, none_symbol):
    if value is None:
        return none_symbol
    return not_none_symbol


# jinja2 custom filters
printing_code = functools.partial(code_to_value, dic={0: "", 1: "○", 2 :"△"})
received_code = functools.partial(code_to_value, dic={0: "", 1: "○", 2 :"△"})
mourning_code = functools.partial(code_to_value, dic={0: "", 1: "○"})
enabled_mark = functools.partial(if_not_none, not_none_symbol="○", none_symbol="")


def dateformat(dt, fmt="%Y-%m-%d %H:%M:%S"):
    return dt.strftime(fmt)


def care_sidebar(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        years = session.query(Year).order_by(Year.year).all()
        if isinstance(result, (dict, DictMixin)):
            if "nav_years" not in result:
                result["nav_years"] = years
        return result
    return wrapper


view = functools.partial(jinja2_view,
            template_settings={
                "filters": {
                    "printing_code": printing_code,
                    "received_code": received_code,
                    "mourning_code": mourning_code,
                    "enabled_mark": enabled_mark,
                    "datefmt": dateformat,
                },
                "globals": {
                    "url": url,
                },
            })


@get("/", name="index")
@view("index.html")
@care_sidebar
def index():
    items = session.query(Person).\
                options(joinedload(Person.available)).\
                options(joinedload(Person.addresses)).\
                filter(Person.disabled==0).\
                order_by(Person.id).all()
    return dict(items=items)


@get("/nenga/list/<year:int>", name="nenga_list")
@view("nenga_list.html")
@care_sidebar
def nenga_list(year):
    items = session.query(Nenga).\
                options(joinedload(Nenga.address)).\
                filter_by(year=year).\
                order_by(Nenga.id).\
                all()
    return dict(year=year, items=items)


@post("/nenga/list/<year:int>", name="nenga_bulk_edit")
def nenga_bulk_edit(year):
    action = request.forms.bulkaction
    # submit ボタンの value 値はあらかじめ
    # "<column_name>_<column_value>" になるように構成しておく
    column_name, value = action.split("_")
    target_ids = [int(item) for item in request.forms.getall("target")]

    targets = session.query(Nenga).filter(Nenga.id.in_(target_ids))
    column = getattr(Nenga, column_name)
    targets.update({column: int(value)}, synchronize_session=False)
    session.commit()
    return redirect(url("nenga_list", year=year))


@get("/person/add", name="person_add_page")
@view("person_add.html")
@care_sidebar
def person_add_page():
    return dict()


@post("/person/add", name="person_add")
def person_add():
    p = Person()
    p.family_name = request.forms.family_name
    p.given_name = request.forms.given_name
    p.disabled = 0
    session.add(p)
    session.commit()
    return redirect(url("index"))


@get("/person/<person_id:int>/address/list", name="address_list")
@view("address_list.html")
@care_sidebar
def address_list(person_id):
    items = session.query(Address).\
                options(joinedload(Address.available)).\
                filter_by(person_id=person_id).\
                order_by(Address.id)
    return dict(person_id=person_id, items=items)


@get("/person/<person_id:int>/address/add", name="address_add_page")
@view("address_add.html")
@care_sidebar
def address_add_page(person_id):
    p = session.query(Person).filter_by(id=person_id).one()
    addr = Address()
    addr.person_id = p.id
    addr.family_name = p.family_name
    addr.given_name = p.given_name
    addr.joint_name1 = ""
    addr.joint_name2 = ""
    addr.zipcode = ""
    addr.address1 = ""
    addr.address2 = ""
    return dict(item=addr)


@post("/person/<person_id:int>/address/add", name="address_add")
def address_add(person_id):
    addr = Address()
    addr.person_id = person_id
    addr.family_name = request.forms.family_name
    addr.given_name = request.forms.given_name
    addr.joint_name1 = request.forms.joint_name1
    addr.joint_name2 = request.forms.joint_name2
    addr.zipcode = request.forms.zipcode
    addr.address1 = request.forms.address1
    addr.address2 = request.forms.address2
    session.add(addr)
    session.commit()
    return redirect(url("address_list", person_id=person_id))


@post("/person/<person_id:int>/address/action", name="address_action")
def address_action(person_id):
    action = request.forms.action
    if action == "activate":
        return address_activate(person_id)
    elif action == "delete":
        return address_delete(person_id)
    else:
        raise ValueError("invalid action:", action)


def address_activate(person_id):
    chosen_id = int(request.forms.chosen)
    addrs = session.query(Address).filter_by(person_id=person_id).all()
    for addr in addrs:
        if addr.id == chosen_id:
            available = session.query(AvailableAddress).filter_by(person_id=person_id).first()
            if available is None:
                available = AvailableAddress()
                available.person_id = person_id
            available.address_id = addr.id
            session.add(available)
            session.commit()

    return redirect(url("address_list", person_id=person_id))


def address_delete(person_id):
    chosen_id = int(request.forms.chosen)
    addr = session.query(Address).filter_by(id=chosen_id).one()
    if addr.available:
        return redirect(url("address_list", person_id=person_id))
    session.delete(addr)
    session.commit()
    return redirect(url("address_list", person_id=person_id))


@get("/nenga/<nenga_id:int>/edit", name="nenga_edit")
@view("edit.html")
@care_sidebar
def edit_page(nenga_id):
    item = session.query(Nenga).filter_by(id=nenga_id).one()
    return dict(item=item)


@get("/static/<filepath:path>", name="static_file")
def static(filepath):
    return static_file(filepath, root="views/static")

###################### UTILITIES

class CSVWriter(object):
    """ ref: http://docs.python.jp/2/library/csv.html
    """
    def __init__(self, f, dialect=csv.excel, encoding="utf-8", **kwargs):
        self.queue = StringIO()
        self.writer = csv.writer(self.queue, dialect=dialect, **kwargs)
        self.stream = f
        self.encoding = encoding

    def write(self, row):
        # 一度 utf-8 としてキューに書いてから、それを読み出して指定のエンコーディングで書き直す
        self.writer.writerow([s.encode("utf-8") for s in row])
        data = self.queue.getvalue()
        data = data.decode("utf-8")
        self.stream.write(data)
        # キューをクリア
        self.queue.truncate(0)

    def writerows(self, rows):
        [self.write(row) for row in rows]


def export_genenga_csv(args):
    targets = session.query(Nenga).filter_by(year=args.year).order_by(Nenga.id).all()

    with io.open(args.output, mode="w", encoding=args.encoding) as f:
        writer = CSVWriter(f, encoding=args.encoding)
        for target in targets:
            flag = 0
            if args.later_only:
                if target.printing == 2:
                    flag = 1
            else:
                if target.printing > 0:  # i.e. 1 or 2
                    flag = 1

            if args.exclude_mourning:
                if target.mourning == 1:
                    flag = 0

            row = [
                str(flag),
                target.address.family_name,
                target.address.given_name,
                target.address.joint_name1,
                # genenga は joint_nama2 をサポートしていない
                target.address.address1,
                target.address.address2,
            ]
            # genenga が要求するCSVでは zipcode を 1 桁ずつカラム分割することが必要。
            # max747 パッチ適用版では zipcode をそのまま渡せる。
            # デフォルトではカラム分割を有効にしておく。
            if args.split_zipcode:
                row.extend([c for c in target.address.zipcode])
            else:
                row.append(target.address.zipcode)
            writer.write(row)


###################### ENTRYPOINTS

def run_webapp(args):
    run(host=args.host, port=args.port, debug=args.debug, reloader=args.reload)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--nodbecho", dest="nodbecho", action="store_true")
    subparsers = parser.add_subparsers()

    parser_initdb = subparsers.add_parser("initdb", help="initialize database schema")
    parser_initdb.add_argument("--drop-create", dest="drop_create", action="store_true")
    parser_initdb.set_defaults(func=initdb)

    parser_nextyear = subparsers.add_parser("nextyear", help="initialize nenga data for next year")
    parser_nextyear.set_defaults(func=init_nextyear)

    parser_genenga = subparsers.add_parser("genenga", help="export genenga compatible csv")
    now = datetime.now()
    if now.month == 1:
        default_year = now.year
    else:
        default_year = now.year + 1
    parser_genenga.add_argument("-o", dest="output", required=True)
    parser_genenga.add_argument("--encoding", dest="encoding", default="utf-8")
    parser_genenga.add_argument("--year", dest="year", type=int, default=default_year)
    parser_genenga.add_argument("--later-only", dest="later_only", action="store_true")
    parser_genenga.add_argument("--include-mourning", dest="exclude_mourning", action="store_false")
    parser_genenga.add_argument("--nosplit-zipcode", dest="split_zipcode", action="store_false")
    parser_genenga.set_defaults(func=export_genenga_csv)

    parser_run = subparsers.add_parser("webapp", help="run as web application")
    parser_run.add_argument("--host", dest="host", default="localhost")
    parser_run.add_argument("--port", dest="port", type=int, default=8080)
    parser_run.add_argument("--nodebug", dest="debug", action="store_false")
    parser_run.add_argument("--noreload", dest="reload", action="store_false")
    parser_run.set_defaults(func=run_webapp)

    args = parser.parse_args()

    engine.echo = not args.nodbecho
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
