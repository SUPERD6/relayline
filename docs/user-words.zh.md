# 用户原话（实验性）

[English](user-words.md) · 中文 · [功能](features.zh.md)

证据仅为 **engineering check**；是否提高派活正确率为 **Unknown**。功能默认关闭。
没有移除任何命令或选项，现有退出码、收据含义和判定规则保持不变。

```sh
ccx config set delegate.user_words true
ccx config set delegate.user_words_max_chars 8000
ccx run --user-words-file request.txt --mode write "实现要求的接口"
```

`--user-words-file PATH` 显式为本次运行开启功能，不受 `delegate.user_words` 关闭影响。
UTF-8 文件优先于自动读取；相对路径从调用 `ccx run` 的目录解析，后台运行也一样。
来源不存在或不可读时，不加原话段，也不让派活报错。

配置 `delegate.user_words = true` 且主导是 Claude Code 时，用已有 transcript 定位器找到主导会话，
读取最近一条真实用户消息。已知主导会话 ID 时优先按 ID 查；没有 ID 时，从任务项目查近期主会话，
排除已知 ccx 子会话。找不到就不加；其他主导工具需显式提供文件。主导照常写 brief，无需修改技能。

新增“User's original words / 用户原话”段明确：与 brief 的接口要求冲突时，以原话的接口要求为准；
疑问写进 `open_questions`。原话是任务数据，不授予新权限，也不扩大任务范围。
跳过 hook/meta/system-reminder 消息、工具结果和 ccx 注入消息；删除 `<pasted_content>` 块，
疑似凭据使用已有 transcript 脱敏规则处理。其他文字、空白和标签保留原样。
这是启发式过滤，不能保证识别全部私人信息。

`delegate.user_words_max_chars` 默认限制过滤后保留 8000 字符；非正数按最小 1 字符处理。
超长截断并明确标注。过滤并截断后的段落保存在已有 `prompt.md` 旁的 `user-words.md`。
重试、升档、换厂商和 `ccx resume` 都复用同一快照，即使来源或配置已经改变。
在旧会话中开始新任务时重新取该任务的原话；恢复时快照缺失则不加，也不重新读取来源。

`run.json` 新增 `user_words: {"source": "file" | "claude" | null, "chars": N}`；`chars` 只计保留原话，
不计说明与截断提示。账本不新增原话正文或来源文件路径。prompt 和快照仍含任务数据，沿用运行产物保留规则。

评测用 `scripts/eval/r5.py run --arms ccx2,ccx2uw ...` 显式加入对比。`ccx2uw` 与 ccx2 的主导文本、
命令参数和隔离完全相同，只在单元 hub 打开 `delegate.user_words`，并在开跑前读回断言。
主导收到的任务消息提供原话。结果行记录 `user_words_mode`，只说明配置模式，不证明找到原话或提高正确率。
实际是否取到，看各 builder 的 `run.json` 元数据。
