# tierlane

Route AI tasks to the cheapest CLI that can handle them — and keep your source
files off third-party clouds unless you explicitly say otherwise.

No dependencies. One config file. Python 3.11+.

```console
$ tierlane "translate this changelog entry to Japanese"
[tierlane → ollama] 0.4s          # free, local, never left the machine

$ tierlane "review the error handling in this module"
[tierlane → claude-haiku] 6.2s    # routed up, because "review" earns it
```

---

## The problem

If you have more than one AI CLI installed, every task goes to whichever one
you typed. That means two things quietly go wrong:

1. **Cheap work runs on expensive models.** Reformatting a docstring does not
   need a frontier model, but that is where it lands, because that is the
   command your fingers know.
2. **Your code leaves the machine without you deciding.** The moment you attach
   a file to a cloud-backed CLI, its contents are on someone else's server. If
   that file happened to contain a live key, so is the key.

tierlane puts a decision in front of both.

## Install

```bash
pip install tierlane
```

Or from source:

```bash
git clone https://github.com/MRL-mana/tierlane
cd tierlane
pip install -e .
```

## 60-second start

```bash
cp tierlane.example.toml tierlane.toml
```

Open it and delete the tiers you do not have installed. Then check what would
happen before anything runs:

```console
$ tierlane "summarize the changes in this file" --dry-run
{
  "selected_tier": 1,
  "tier_name": "gemini-flash",
  "cloud": true,
  "would_send_files": false,
  "blocked": false,
  ...
}
```

`--dry-run` never calls a backend. Use it while you are tuning the rules.

---

## The guard

This is the part that is not just a shell alias.

**Files are scanned before they are sent.** Nine credential patterns —
GitHub, Slack, OpenAI, AWS, Google, private keys, JWTs, inline
`api_key = "..."` assignments:

```console
$ tierlane "explain this" --files db.py --allow-cloud
[tierlane] blocked: OpenAI key found in /home/you/app/db.py — refusing to send it.
```

The scan runs against the **whole file, before truncation**. A key sitting past
the context budget would otherwise be dropped from the payload by the
truncation step and never checked — which looks safe, but only because the
guard stopped looking.

**Cloud tiers need consent to carry your files.**

```console
$ tierlane "summarize this" --files app.py
[tierlane] blocked: This tier sends your file contents to a third-party cloud
API. Re-run with --allow-cloud if that is what you want.
```

Note what is *not* gated: a bare task string with no `--files`. You wrote that
string, so you already know what is in it. File contents are different — the
tool pulled them in, and they can hold code you never opened.

**Reads are sandboxed to directories you name.**

```console
$ tierlane "summarize" --files /etc/shadow
[tierlane] blocked: /etc/shadow is outside the allowed read roots.
Pass --allow-root to widen them.
```

**Some tasks are never delegated at all.**

```console
$ tierlane "deploy to production"
Held. This task matches a `hold` keyword, so it was not delegated —
handle it yourself.
```

The point of `hold` is not that a model would refuse. It is that you should not
be pasting back the output of a subprocess you did not read for work of that
consequence.

---

## Configuration

Everything about *which* CLIs exist lives in `tierlane.toml`, so adding a
backend never means editing the router.

```toml
[[tier]]
level = 0
name = "ollama"
kind = "http"                      # OpenAI-compatible /chat/completions
endpoint = "http://127.0.0.1:11434/v1/chat/completions"
model = "qwen2.5-coder:7b"
cloud = false                      # stays on this machine

[[tier]]
level = 2
name = "claude-haiku"
kind = "cli"                       # runs as a subprocess
command = ["claude", "-p", "{prompt}", "--model", "haiku", "--output-format", "text"]
cloud = true                       # --files needs --allow-cloud
```

`{prompt}` places the task on the command line. Leave it out and the prompt
arrives on **stdin** instead, which is what you want for long contexts that
would blow past your shell's argument limit.

Routing rules are substring matches against the task:

```toml
[[rule]]
tier = 0
keywords = ["draft", "translate", "template", "format"]

[[rule]]
tier = 2
keywords = ["review", "critique", "refactor", "design"]
```

When a task matches several rules, **the highest tier wins** — `"draft and
review the design"` goes to tier 2, not tier 0. Unmatched tasks fall to the
cheapest tier you defined.

Config is found in this order: `$TIERLANE_CONFIG`, then `./tierlane.toml`, then
`~/.config/tierlane/tierlane.toml` (`%APPDATA%\tierlane\` on Windows).

---

## Escalation

`--escalate` steps up a tier when a result errors or comes back suspiciously
short:

```console
$ tierlane "explain why this test is flaky" --escalate
[tierlane] skipped tier 1 (gemini-flash): cloud tier, no --allow-cloud
[tierlane → claude-haiku] 4.1s · 3 attempts
```

Two design notes:

- **A blocked cloud tier is skipped, not fatal.** The run continues up the
  ladder and keeps any local result it already has.
- **The "too short" threshold is configurable** (`--min-output-chars`). A task
  like *"answer with just the number"* produces a correct three-character
  answer, and failing that upward into a paid tier is exactly the waste this
  tool exists to prevent.

Nested runs are pinned to the cheapest tier and cannot escalate — a backend
that is itself tierlane-aware sees `TIERLANE_CHILD=1` in its environment. Two
routers cannot bounce a task between each other forever.

---

## Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | Success |
| `1` | The backend ran and failed |
| `2` | Held — matched a `hold` keyword |
| `3` | Config error |
| `4` | Blocked by a guard (secret, path, or cloud egress) |
| `130` | Interrupted |

Scripts can tell "the model gave a bad answer" (`1`) apart from "we refused to
send this" (`4`).

---

## Library use

```python
import asyncio
from tierlane import load_config, pick_tier, run

config = load_config()
level = pick_tier("summarize this module", config)
result = asyncio.run(run("summarize this module", level, config))

print(result.tier_name, result.ok, result.output)
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## Why it exists

I ran a local AI setup across several CLI agents and kept hitting the same two
problems: the expensive one got work the cheap one could do, and I could not
tell, after the fact, which files had been sent where. The guard came first;
the cost routing followed.

## License

MIT

---

# 日本語

複数のAI CLIを使っていると、タスクは「その時打ったコマンド」に流れます。結果と
して、安いモデルで足りる作業が高いモデルに行き、ファイルを添付した瞬間にその中身
が外部のサーバーへ出ていきます。鍵が混ざっていれば、鍵も一緒に出ていきます。

tierlane はその2つの前に判断を挟みます。

- **タスク内容から行き先を決める** — 「翻訳」ならローカルLLM、「レビュー」なら上位へ
- **ファイル送信は既定で拒否** — `--allow-cloud` を明示しない限り、外部クラウドへは出さない
- **送る前に9種の認証情報を走査** — 切り詰め前の全文を検査するので、文字数制限の外にある鍵も見逃さない
- **読み取り範囲を限定** — 指定ディレクトリの外は読まない
- **委譲しない作業を決められる** — `hold` に該当したら実行せず手元に戻す

設定は `tierlane.toml` 1本。CLIを足すのにコードを触る必要はありません。依存パッケージ
はゼロ、Python 3.11以降で動きます。
