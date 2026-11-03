# Q-SL1 SEC002 toolkit

**XIAO ESP32C3のLAN中継コードを追加しました。** 玄関のXIAO＋外付けアンテナがBluetoothを受け持ち、ラズパイとは暗号化LANで通信します。登録済み所有者鍵を使うランタイム、XIAOの設定・USB書き込み、ラズパイの常駐、HomeKitへの接続を収録しています。[中継のセットアップ手順](relay/README.ja.md) ／ [コード一覧](relay/)。1個体でPiを離した状態のiPhone施錠と正常完了を確認済みです。

中継コードは最新ソースに含まれます。既存の`v0.1.0` Release ZIPはSEC002用の配布物で、中継コードは含みません。下記の「全無線導入は未検証」は、Q-SL1本体へのSEC002初回インストーラーを指します。

初代Qrio Smart Lock Q-SL1向けの独自差分パッチと、Linux／ラズパイのBluetoothから初回導入するためのツールです。純正ファーム・個体バックアップ・所有者鍵は含みません。独自部分はMIT Licenseです。

**実験版です。この配布版による純正→SEC002の全無線導入は、実機で最初から最後まで試していません。** SEC002自体の有線導入・動作と、別候補での無線転送・起動切替を、所有する1個体で別々に確認しています。

- [実験版Release・ダウンロード](https://github.com/bruiselea/qrio-sec002/releases/tag/v0.1.0)
- [配布ZIP](dist/qrio-sec002-toolkit-v0.1.0.zip) ／ [SHA256SUMS](dist/SHA256SUMS.txt)
- [配線なし初回導入の全手順](docs/WIRELESS_INSTALL.ja.md)
- [対応条件・確認済み範囲](README.ja.md)
- [中断時の判断・有線復旧の準備](docs/RECOVERY.ja.md)
- [ライセンスと配布範囲](NOTICE.md) ／ [検証方法](docs/TESTING.ja.md)

対象は既知の純正`1.4.01`と同じDS1ハッシュ・配置の未改造機だけです。Q-SL1との初回接続には配線を使いません。WindowsからはLinuxホストをSSHで操作できます。

**SEC002導入後のファーム更新・起動障害からの救済は有線UART限定です。** 自動起動ロールバックはなく、UART救済プログラムもこの配布物には含みません。電波が出ない本体を無線で復旧するツールではありません。

施解錠やHomeKitの所有者登録は別途必要です。既存の個体情報を保持する設計ですが、このキットだけで新しい所有者鍵やHomeKit環境は作成しません。

## オフライン検査

Python 3.11以上で、Bluetoothや純正ファームを使わずに合成テストを実行できます。

```sh
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
python -m qsl1sec --help
```

WindowsとラズパイのLinuxで11件の試験を確認しています。全実機・全電源断条件・防犯性能全般の保証ではありません。
