# カードから所有者登録し、操作鍵を用意する

自分のQ-SL1とオーナー登録カードを使い、新しい操作鍵を本体へ登録するローカルツールです。登録前に全鍵を暗号化vaultへ保存し、登録後に**別接続で認証付きReadStatusが成功した場合だけ**`owner.json`を出力できます。施解錠・ファーム更新・メモリー書き込み・既存所有者削除のコマンドは含みません。

登録・認証とMQ処理は旧Androidアプリ1.8.7と所有する実機を解析した再実装です。解析元、先行調査、利用ライブラリーは[出典一覧](../SOURCES.md)に記載しています。

**公開版の新規登録は実機通し試験未実施です。** 手元の個体で使った登録プロトコルを整理し、合成した通信相手で正常系・通信断・鍵保存を検証しています。既に動いている鍵の再登録には使わず、以前のvaultがある場合は下の「既存vaultから」を選びます。[検証範囲](TESTING.ja.md)を確認してください。

## 必要なもの

| 条件 | 内容 |
| --- | --- |
| 本体とカード | 自分のQ-SL1、正常な電池、その個体のオーナー登録カード。カードのシリアルとセキュリティコードを使用 |
| 物理確認 | 新規登録時はドアから本体を外し、つまみを回せる状態にする |
| 登録用APK | **自分で保管している旧公式Android APK 1.8.7の対応ライブラリー**。下の指紋が一致するものだけを許可 |
| 実行環境 | Python 3.11以上のWindows PC、またはBlueZとD-Busを使えるLinux/Pi |
| 無線 | 実行ホストのBLE、または設定済みXIAO中継器とその私有`relay.private.json` |
| 保存先 | 本人だけが読める、リポジトリ外のローカルフォルダー。共有・クラウド同期フォルダーは避ける |

**カードだけで完結する配布物ではありません。** 新しいMQ公開鍵の生成には、旧APK内の係数表を読み込む必要があります。APK・ネイティブライブラリー・係数表は同梱せず、取得代行や自動ダウンロードも行いません。手元に対応APKがない場合、新規登録はここで止まります。既存vaultの確認・操作鍵の出力・日常の施解錠にAPKは不要です。

対応する`lib/x86_64/libmq.so`のSHA-256:

```text
725f3cbb447eed0a523d0844f371e657a3cc0c21059274dce520997dc3ad67ff
```

APKはインストール・実行しません。指定のZIPメンバーを上限付きで読み、指紋を照合してからELFの`MQ_COEF`をメモリー上で参照します。別版を強制指定する機能はありません。

## 1. 最新ソースと環境を用意

リポジトリのルートで実行します。旧v0.1.0 Release ZIPには`onboarding/`と`relay/`が入っていません。

```sh
git clone https://github.com/bruiselea/qrio-sec002.git
cd qrio-sec002
```

Windows PowerShell:

```powershell
python -m venv .venv-onboarding
.venv-onboarding\Scripts\python -m pip install -r requirements-onboarding.txt
$qrioPrivate = "$env:USERPROFILE\.qrio-sl1\onboarding"
New-Item -ItemType Directory -Force $qrioPrivate | Out-Null
```

Windowsではファイルの保護は保存先のNTFS ACLを継承します。本人以外に読み取り権限のある場所は使いません。暗号化vaultと別に、出力した`owner.json`には平文の操作鍵が入ります。

Linux/Pi:

```sh
umask 077
python3 -m venv .venv-onboarding
.venv-onboarding/bin/python -m pip install -r requirements-onboarding.txt
mkdir -p ~/.config/qrio-relay
chmod 700 ~/.config/qrio-relay
```

以下はWindowsの例です。Linuxでは`.venv-onboarding/bin/python`と`~/.config/qrio-relay/owner.qsl1`などへ置き換えます。LinuxのBLE操作にはBlueZのサービスと本人のD-Busアクセス権が必要です。常用のHomeKitゲートウェイ、純正アプリなど、同じ本体へ接続する処理を止め、同時操作を避けます。

## 2. APKを確認

`C:\path\to\your-archived.apk`を本人のファイルへ置き換えます。

```powershell
.venv-onboarding\Scripts\python -m onboarding inspect-apk --apk "C:\path\to\your-archived.apk"
```

対応指紋が表示されれば読み込み可能です。`ValueError`になった場合は、ファイルの存在・旧版かどうか・対応ライブラリーの有無を確認します。対応外の版のまま登録へ進まないでください。

## 3. 新規登録する

**ドアから外した本体**をBLEホストまたはXIAOの近くへ置きます。登録途中で本体がビープ音を出したら、つまみを90度以上回して戻します。作業中は電池を抜きません。`--device-off-door`はその準備を済ませたことを指定する引数です。

```powershell
.venv-onboarding\Scripts\python -m onboarding enroll --apk "C:\path\to\your-archived.apk" --vault "$qrioPrivate\owner.qsl1" --device-off-door
```

シリアル、カードのセキュリティコード、**ここで自分が新しく決める回復パスフレーズ**を端末へ非表示で入力します。パスフレーズは12文字以上で2回一致することが必要です。日本語・全角・前後の空白を含め、入力した文字をそのまま使います。以前の利用者のパスワードではありません。チャットやコマンド引数へ秘密を貼り付けません。

処理は次の順番です。

1. カードのシリアルに合う広告を探す。対応する識別子が0件または複数なら中断。
2. RSA鍵2組、MQ鍵、共有鍵を生成し、暗号化vaultを新規作成・読み戻して確認。
3. カードとの相互チャレンジを照合してから、**保存済みの公開鍵**を送る。
4. 本体の物理確認・登録応答を受け取り、vaultを`acknowledged`へ更新。
5. 接続を閉じて改めて接続し、保存した鍵でReadStatusを実行。成功時だけ`verified`へ更新。

BLEのJust Worksペアリングは通信路を作る処理で、それだけで所有者として登録されたことにはなりません。カード照合と操作認証を別途行います。

### PCにBluetoothがない場合／XIAOを使う場合

[中継の手順](../relay/README.ja.md)の1〜3と`relay.private.json`の作成までを先に行います。この部分に所有者鍵は不要です。続いて登録コマンドへ、本人の設定ファイルを追加します。

```powershell
.venv-onboarding\Scripts\python -m onboarding enroll --apk "C:\path\to\your-archived.apk" --vault "$qrioPrivate\owner.qsl1" --device-off-door --relay-config "$qrioPrivate\relay.private.json"
```

登録時のカード共有鍵と公開鍵はBLEメッセージとして中継されますが、RSA秘密鍵・MQ秘密鍵・カードコード・vaultパスフレーズそのものはXIAOへ送りません。設定ファイルと暗号化されたAPI接続の管理は[中継の手順](../relay/README.ja.md)に従います。XIAO経由の新規登録も公開版では実機未確認です。

## 4. 操作用owner.jsonを出力

```powershell
.venv-onboarding\Scripts\python -m onboarding export --vault "$qrioPrivate\owner.qsl1" --output "$qrioPrivate\owner.json"
```

このコマンドは本体へ通信せず、検証済みvaultから操作に必要な8項目だけを新しいファイルへ出力します。カードのシリアル、MQ秘密鍵、保管用RSA秘密鍵、パスフレーズは出しません。出力先が既にある場合は上書きしません。

`owner.json`は**施解錠できる平文の秘密情報**です。表示・Git追加・共有をせず、本人のSSH/SFTPでPiの`~/.config/qrio-relay/owner.json`へ転送し、Linuxではモード600にします。[中継の状態取得](../relay/README.ja.md)を確認してから、[systemd credentialとHomeKit](../relay/SYSTEMD_HOMEKIT.ja.md)へ進みます。暗号化vaultは別途保管します。

## 既存vaultから始める場合

以前の`owner-credential.qsl1`がある場合、**別の場所にコピーを保管してから**次を実行します。APKもカードも再登録も不要です。

```powershell
.venv-onboarding\Scripts\python -m onboarding inspect --vault "$qrioPrivate\owner.qsl1"
.venv-onboarding\Scripts\python -m onboarding verify --vault "$qrioPrivate\owner.qsl1"
.venv-onboarding\Scripts\python -m onboarding export --vault "$qrioPrivate\owner.qsl1" --output "$qrioPrivate\owner.json"
```

本人が最初に設定した回復パスフレーズを入力します。`verify`は認証付きReadStatusだけを行い、モーターを動かしません。XIAO経由なら`verify`にも`--relay-config`を付けます。以前の`registered`表示は登録応答の確認だけの場合があるため、そのままの状態では出力しません。`verified`になる必要があります。

## 中断・エラーのとき

| 状況 | 次の行動 |
| --- | --- |
| パスフレーズ／形式エラー | `inspect`で確認。大文字・全角・空白を最初の入力と合わせる。vaultは削除しない |
| 本体が見つからない | 電池・距離・他の接続・ローカルBLEまたはXIAO設定を確認 |
| 登録がタイムアウト／応答を失った | **まず`verify`**。最後の応答だけ失っていても認証が通る可能性がある |
| `verify`も通らず部分登録を再開したい | 同じvaultを使い、上の`enroll`へ**`--resume`**を追加。同じカード・対応APK・物理確認も必要 |
| 状態が`acknowledged` | 登録応答は確認したが操作認証は未確認。`export`は拒否される |
| `status=130`／`132`など | 拒否を成功扱いしない。vaultを保管し、接続・物理確認・登録状態を調べる |
| 出力先が存在する | 新しい出力名を指定。既存の操作鍵やvaultを上書きしない |

自動再試行・自動的な鍵の作り直しは行いません。`--resume`は保存済みの鍵だけを再使用します。`verified`／旧`registered`のvaultでは直接の再登録を拒否し、先に`verify`を使います。新しい`verify`が失敗した場合、古い検証済み印も外して`acknowledged`へ戻し、再確認できるまで出力を止めます。その状態からの再登録は、本人が明示的に`--resume`を指定したときだけ行います。

更新前の暗号化データは`owner.qsl1.backup-...`として残し、更新本体は同じディレクトリーの一時ファイルから原子的に置き換えます。`.lock`は同じvaultの同時使用を防ぐOSロック用の小さなファイルです。終了後も残りますが、ロックはOSが解放します。これらとvaultは公開しません。パスフレーズを忘れた場合の総当たり・解除機能はありません。
