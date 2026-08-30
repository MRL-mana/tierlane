# tierlane

日本語 | [English](README.md)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://github.com/MRL-mana/tierlane/actions/workflows/test.yml/badge.svg)](https://github.com/MRL-mana/tierlane/actions/workflows/test.yml)

AIの仕事を、内容と費用に合わせて最適なCLIへ振り分けます。ソースファイルをクラウドへ送るときは、明示的な許可が必要です。

依存パッケージなし。設定ファイル1つ。Python 3.11以上。

```console
$ tierlane "この変更履歴を日本語にして"
[tierlane → ollama] 0.4s          # 無料・ローカル・外部送信なし

$ tierlane "このモジュールのエラー処理をレビューして"
[tierlane → claude-haiku] 6.2s    # レビューなので上位モデルへ
```

## 解決すること

複数のAI CLIを使っていると、簡単な整形まで高価なモデルへ送りがちです。さらに、ファイルを添付した瞬間に、確認していないコードや認証情報まで外部へ送る危険があります。

tierlaneは、その2つを実行前に判断します。

- 軽い仕事は安価なローカルAIへ
- レビューや設計は必要な上位モデルへ
- ファイル全体を秘密情報パターンで検査
- クラウドへファイルを送る場合は `--allow-cloud` が必須
- 許可したフォルダ外の読み取りを拒否
- 公開・本番反映などの重要作業はAIへ委譲せず保留

## インストール

```bash
pip install "tierlane @ git+https://github.com/MRL-mana/tierlane.git@v0.1.0"
```

現在PyPIには未公開です。上記はGitHubの公開版v0.1.0を直接導入します。

開発する場合:

```bash
git clone https://github.com/MRL-mana/tierlane
cd tierlane
pip install -e ".[dev]"
pytest
```

## 60秒で試す

設定例をコピーします。

```bash
cp tierlane.example.toml tierlane.toml
```

使用していないAIの設定を削除し、まず実行せずに振り分け結果だけ確認します。

```bash
tierlane "このファイルの変更点を要約して" --dry-run
```

`--dry-run` はAIを呼び出しません。ルール調整中も費用や外部送信は発生しません。

## ファイル送信の安全確認

```console
$ tierlane "説明して" --files db.py --allow-cloud
[tierlane] blocked: OpenAI key found in db.py — refusing to send it.
```

検査は切り詰める前のファイル全体に対して実行します。GitHub、Slack、OpenAI、AWS、Google、秘密鍵、JWT、`api_key = "..."` 形式などを検出します。

クラウドのAIへファイルを渡す場合:

```bash
tierlane "このコードをレビューして" --files app.py --allow-cloud
```

`--allow-cloud` がない場合は送信せず停止します。依頼文だけでファイルを付けない場合は、この確認の対象外です。

## 設定例

```toml
[[tier]]
level = 0
name = "ollama"
kind = "http"
endpoint = "http://127.0.0.1:11434/v1/chat/completions"
model = "qwen2.5-coder:7b"
cloud = false

[[tier]]
level = 2
name = "claude-haiku"
kind = "cli"
command = ["claude", "-p", "{prompt}", "--model", "haiku", "--output-format", "text"]
cloud = true

[[rule]]
tier = 0
keywords = ["下書き", "翻訳", "整形"]

[[rule]]
tier = 2
keywords = ["レビュー", "設計", "リファクタ"]
```

複数ルールに一致した場合は、最も高いtierを選びます。一致しない仕事は、設定済みの最も安いtierへ送ります。

## 終了コード

| コード | 意味 |
| ---: | --- |
| `0` | 成功 |
| `1` | AIの実行が失敗 |
| `2` | 重要作業のため委譲せず保留 |
| `3` | 設定エラー |
| `4` | 秘密情報・パス・クラウド送信の安全確認で停止 |
| `130` | 中断 |

## ライセンス

[MIT License](LICENSE)
