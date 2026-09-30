# 参考图更换后生成行为审查

审查日期：2026-09-30。范围：前端删除/上传/提交、参考图暂存和云端上传、工作流绑定、ComfyUI 历史、二采来源。

## 当前任务的已验证结论

- 当前分镜为 `CAMPUS10_01`。公共参考层关闭，`continue_from_previous=false`。
- 旧图已从本次请求移除；22:31 和 22:41 两次请求都仅包含 `Qwen_image_2_1_00001_f9f09a275dc8.png`、`Qwen_image_2_1_00004_98c9f44c526c.png`。
- 不仅检查本地 run.json，还读取云端 `http://192.168.11.103:8188` 的真实历史工作流及 `/view?type=input` 图片字节。LoadImage 151/152 确实使用新图，其 SHA-256 分别为：
  - `f9f09a275dc8b2362637584d3aaacfd17127d0c2d62dbb85a072fd79c0c7ce04`
  - `98c9f44c526c518be1ed4f322c876ac7fdb15ee23adcf63e82fd14c52fa8f379`
- 22:31 的 prompt_id 为 `93fcbeb3-5576-4971-84e0-592a4330b46e`。execution_cached 不包含 LoadImage 151/152、参考条件 136、采样 125：新图条件和采样实际重新执行，耗时约 424 秒。
- 22:41 的 prompt_id 为 `080cc8a3-0e81-4e1c-8cb0-6d7e3043cf57`。所有关键节点（包括保存节点 92）都命中缓存，约 9 毫秒结束，返回与 22:31 相同的 `CAMPUS10_01_breeze_4shots_00003_.mp4`。图片、提示词、种子等输入相同，因此这是重复请求的结果缓存，不能作为仍使用删除前旧图的证据。
- 当前提示词仍明确、反复要求旧服装（navy blazer、white collared shirt、blue plaid pleated skirt 等），并将 wardrobe 设为 fully_preserved。新图与这些文字约束存在冲突。可确认冲突存在；模型实际如何权衡图文，不能仅凭代码断言。

## 代码发现

### P1：新一采完成后，二采仍可能沿用旧二采链

位置：`app/static/app.js` 的 `submitRefine`、`submitShot`，及 `app/main.py` 的 `submit_refine`。

`submitRefine` 只要看到 `s.refine_job.status==='completed'`，就使用该旧 refine_job.output_name 作为来源。`submitShot` 接受新一采后没有清理或标记旧 refine_job 属于上一轮。当前项目曾有 p3 二采结果，此分支会选择旧 p3 的 latent，而不是换图后新一采的 latent。点击任意结果卡的二采按钮也仅提交分镜，不指定该结果。

建议：记录一采生成版本与 latent 来源绑定关系；新一采成功提交后终止旧二采链的默认继承，显式保留旧结果供选择。二采来源应绑定具体结果/版本，并有后端校验。本发现影响二采，无法解释已核验的新一采图像加载。

### P2：图片变化后没有提示用户核对旧文字约束

位置：`uploadImages`、`renderRefs`。

添加/删除图片仅改变 references、status 并安排保存。旧提示词中的外观描述和 Picture 编号不会同步，也没有标记需核对。本次保留旧服装描述就是实际例子。

建议：素材删除、替换或重排后显示提示词核对提示，展示最终参考编号；避免自动改写用户文案。

### P2：重复点击生成可能只返回同一缓存视频

位置：`submitShot`、`build_workflow`。

种子固定，相同参数构成相同工作流。22:41 已证实完全复用上一任务视频；页面仍按新任务显示排队/完成。与技能声明“每次生成新增结果”的行为不一致。

建议：明确提供固定种子复现与新随机种子重生成选项；结果收集和界面应识别本次是否复用已有输出，避免表示为新采样。

### P2：上传未完成时可提交旧 references

位置：`uploadImages` 和 `submitShot`。

上传完成前不更新 references，提交入口也没有检查待完成上传，因此在上传期间点击生成会提交当时旧数组。本次 22:31、22:41 的历史均是新数组，所以不是这两次任务的原因。

建议：按分镜追踪图片/视频/音频上传状态，所有生成入口等待上传成功再取提交快照；失败时阻止提交并显示失败信息。

## 验证与边界

- `python -m pytest tests/test_storage.py tests/test_workflow.py tests/test_playlist.py tests/test_frontend_polling.py -q`：113 通过，1 失败。
- 失败为 `test_build_refine_workflow_uses_h3_av_latent_upscale_and_low_noise_sample`：默认工作流没有测试预期的节点 305。此失败发生在本次零代码修改的工作区，属于现存二采实现/测试预期不一致，未证实与换图问题有关。
- 本次为只读代码审查，新增此报告；未修改应用代码、故事板、任务、图片或结果，未提交生成任务，也未重启服务。
- 运行记录支持“新图正确送达，提示词仍保留旧约束，以及第二次完全复用第一次新图任务缓存”。尚未通过受控生成实验确定模型呈现旧造型的唯一原因。
