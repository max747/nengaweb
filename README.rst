nengaweb
========

What's this?
------------

年賀状の宛名を管理するWebUI


Feature
-------

* 住所変更履歴の記録
* 年度単位での送付、受領、喪中の管理
* `Genenga <https://github.com/mkouhei/Genenga>` 互換CSVの出力

Require
-------

* Python 2.7.x
* Python 3.x での動作は未確認

Quickstart
----------

::

 git clone https://github.com/max747/nengaweb
 cd nengaweb
 (もし必要ならば virtualenv などで独立した環境を作って)
 pip install -r require.txt
 python app.py initdb
 python app.py webapp

