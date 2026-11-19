# cli-anything-index

离线编译一份 CLI-Anything 检出目录的能力索引：每个 harness 的软件名、SKILL.md 元数据、解析器里的真实命令与 flag、以及 SKILL.md 声称存在的命令，全部落成一个可查询的 `index.json`——不联网、不 import 任何 harness、不执行任何外部软件。

**为什么现在需要它**：CLI-Anything 已有 100+ 个 `agent-harness`，但 agent 要发现它们只能装 `cli-anything-hub` 走 PyPI/网络；而它自己 README 的 Limitations 承认覆盖度得靠反复 `/refine` 才「可能」达标。也就是说，**文档说有哪些命令、解析器里到底有没有，没有任何离线手段可以核对**。

Upstream: https://github.com/HKUDS/CLI-Anything

## 上游是什么，缺什么

CLI-Anything（`HKUDS/CLI-Anything`，Apache-2.0）把桌面软件包装成 CLI harness，每个软件一个 `<软件>/agent-harness/`，内含 `cli_anything/<pkg>/<x>_cli.py` 与 `skills/SKILL.md`。

- 发现/安装路径依赖网络与 pip 包：README 只给出 `pip install cli-anything-hub` + `cli-hub install <name>`（[README#L12](https://github.com/HKUDS/CLI-Anything/blob/main/README.md#L12)）。
- 覆盖度是自认的未知量：Limitations 写「A single `/cli-anything` run may not fully cover all capabilities… Running `/refine` … to push … coverage to production quality」（[README#L1735](https://github.com/HKUDS/CLI-Anything/blob/main/README.md#L1735)）。
- 仓库里没有任何机器可读的能力清单：`skills/` 只是 SKILL.md 的镜像目录（[tree](https://github.com/HKUDS/CLI-Anything/tree/main/skills)），没有命令级索引，也没有把 SKILL.md 与解析器对齐的离线工具。

因此「它生成 CLI 并由 SKILL.md 教 agent 调用，但没人能离线核对文档里的命令是否真在解析器里」是一个可验证的缺口。

## 这个工具做什么

- `index`：扫描 `<软件>/agent-harness`，静态解析 `*_cli.py`（click / argparse 的 AST，不 import），抽取命令、flag、`--json` 支持，并解析 SKILL.md frontmatter 与文档中出现的命令。
- `check`：输出 finding（`no-skill` / `no-cli-source` / `cli-syntax-error` / `parser-unparsed` / `no-json-flag` / `documented-not-in-parser`），有 error 时退出码 1。
- `query`：按软件名或「是否支持 `--json`」过滤索引。

**不做什么**：不运行 harness、不调用外部软件、不判断命令的运行时正确性；`documented-not-in-parser` 是「待人工复核」的提示，不等于上游 bug。不联网，不读 `$HOME`，不写除 `--out` 指定文件外的任何路径。

## 安装 / 用法

零第三方依赖，Python ≥ 3.10：

```bash
git clone git@github.com:linmoxi33/cli-anything-index.git
cd cli-anything-index
python3 bin/cli-anything-index index --root /path/to/CLI-Anything --json --out /tmp/index.json
python3 bin/cli-anything-index check --root /path/to/CLI-Anything
python3 bin/cli-anything-index query --root /path/to/CLI-Anything --software blender --json
```

`--root` 必须是 CLI-Anything 检出根目录（其下有 `<软件>/agent-harness`），否则退出 2。

### `--json` 输出示例

```json
{
  "schema_version": 1,
  "totals": {"harnesses": 2, "parser_commands": 2, "with_json_flag": 2},
  "entries": [{"software": "cad", "framework": "click", "commands": ["draw"],
               "documented_commands": ["draw"], "json_flag": true}]
}
```

完整样例见 `examples/in/`（一个两 harness 的迷你检出）与 `examples/out/index.json`、`examples/out/check.json`。

### 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 成功；`check` 没有 error 级 finding（warn 不影响） |
| 1 | `check` 检出 error 级问题；`query` 无匹配 |
| 2 | 用法错误或 `--root` 不是 CLI-Anything 检出 |

## 实测（真实检出，非合成数据）

对上游 commit `34f5195`（2026-09-22）抽样 16 个 harness 的 `SKILL.md` + `*_cli.py`（`3MF`、`blender`、`audacity`、`calibre`、`freecad`、`QGIS`、`zotero`、`n8n`、`shotcut`、`kdenlive`、`libreoffice`、`inkscape`、`gimp`、`obsidian`、`iterm2`、`drawio`）：

```text
harnesses: 16  skills: 16  cli sources: 16
parser commands: 845  documented commands: 70
--json flag: 16/16
findings: warn=4, error=0
```

4 条 warn 全部是 `documented-not-in-parser`（freecad/inkscape/libreoffice 的 `project`、freecad 的 `output`），即 SKILL.md 里出现的命令名在解析器命令表中找不到；它们是待复核信号，本工具不替上游判定真伪。复现命令：

```bash
python3 bin/cli-anything-index check --root /path/to/CLI-Anything --json
```

## 与同类项目的差异

`gh search repos "cli-anything"` 只命中上游本体与若干 harness 移植；`gh search repos "cli capability index"` 无结果。CLI-Hub 是**联网的安装注册表**（pip 包 + 网页），本工具是**离线、只读的能力索引**；`npx skills add` 只负责安装 SKILL.md，不核对命令是否存在。二者都不产出「文档命令 ↔ 解析器命令」的对账数据。

## 本轮创新

首次把 CLI-Anything 的「能力发现」从联网注册表下移到一份离线可查询的索引，并首次在真实检出上量化 SKILL.md 命令与解析器命令的覆盖差（16 个 harness：845 条解析器命令、70 条文档命令、4 条文档命令在解析器中不存在）。与台账中的静态 schema 审计不同，这里对账的是「人类写给 agent 的调用文档」与「程序真正接受的命令表」。

## 局限

- SKILL.md 是散文，命令抽取是启发式：`--flag value` 按「已知布尔 flag 之外都吃一个值」处理，可能漏掉或误报，故 `documented-not-in-parser` 只作 warn。
- 只解析 click / argparse；自定义 dispatch 或 Typer 会落入 `parser-unparsed`。
- 静态解析，不验证运行时行为、参数类型或副作用。
- 抽样 16 个 harness 的实测数字不代表全仓 141 个 harness。

## 测试

```bash
python3 -m unittest discover -s tests -v   # 19 tests, 全部离线
```

## License

MIT，见 `LICENSE`。上游 CLI-Anything 为 Apache-2.0；本仓库不包含上游代码，仅在运行时读取用户本地的检出目录。