import copy
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(r"G:\AI短剧生成")
PROJECT = ROOT / "憋住世界就停了_Ref2VA_480p_V2"
BOARD = ROOT / "comfyui-ref2va-tool" / "data" / "storyboard.json"
FRAMES = PROJECT / "01_分镜首帧"
ROLES = PROJECT / "02_角色资产"
ASSETS = PROJECT / "03_场景道具资产"
DOCS = PROJECT / "04_分镜与提示词"

P = lambda p: str(p)
chen = P(ROLES / "角色01_陈小凡_四栏身份板.png")
boss = P(ROLES / "角色02_赵老板_四栏身份板.png")
lin = P(ROLES / "角色03_林雨_四栏身份板.png")
qi = P(ROLES / "角色04_齐博士_四栏身份板.png")
car = P(ASSETS / "资产01_事故汽车_四视图.png")
street = P(ASSETS / "资产02_斑马线街道_场景板.png")
office = P(ASSETS / "资产03_开放办公室_场景板.png")
bins = P(ASSETS / "资产04_垃圾桶组三视图.png")
lottery = P(ASSETS / "资产05_财务桌与彩票机_场景板.png")
transition = P(ASSETS / "资产06_电梯食堂楼梯_过渡场景板.png")
training = P(ASSETS / "资产07_训练空间组合场景板.png")
water = P(ASSETS / "资产08_量子气泡水道具板.png")
lab = P(ASSETS / "资产09_齐博士实验室_场景板.png")
props = P(ASSETS / "资产10_关键小道具组合板.png")
old = lambda n: P(FRAMES / f"S{n:02d}_首帧.png")
v3 = lambda name: P(FRAMES / name)

specs = {
"S01": ("r2va", False, True, [v3("S01_首帧_V3.png"), chen, lin, street, car],
"暖色街道危机转冷蓝冻结；不提前展示男主", "中近景跟拍林雨正常急走，汽车高速逼近。她听见引擎后立即惊慌回头并本能躲闪，不能发愣，汽车不能刹车。车头距她约三十厘米且尚未接触时，超自然低频‘咚’响起，时间瞬间冻结并由暖色硬切冷蓝。随后镜头弧移到路旁，揭示面向事故现场、闭嘴鼓腮、脸微红的陈小凡；除他轻微憋气颤抖外一切绝对静止。汽车始终不能撞上、不能在冻结后继续前进。", "高速引擎、心跳和短促惊呼在‘咚’声后骤停，只留暂停嗡鸣与内心旁白。"),
"S02": ("fl2va", True, True, [v3("S02_尾关键帧_V3.png"), chen, lin, street, car],
"承接冻结现场，男主拖走刚体般的女孩", "严格承接上一镜latent的冷蓝冻结状态和人物方位。陈小凡始终闭嘴鼓腮，狼狈抱住林雨上身向安全路边后退拖移；林雨是完全僵硬的刚体，不走路、不眨眼、不呼吸、不主动平衡，只有被外力整体移动。汽车、反射、衣发和背景全部静止。结尾对齐Picture 1：陈小凡抱稳僵硬林雨，仍面向事故方向，留出下一镜翻滚动势。", "仅有用力闷哼、鞋底刮擦、心跳和低频暂停嗡鸣。"),
"S03": ("r2va", True, False, [chen, lin, street, car, bins],
"承接抱拖落点，吐气后恢复并滚入垃圾桶", "严格承接上一镜latent。开场仍为冷蓝冻结，陈小凡闭嘴鼓腮抱住僵硬林雨；他第一次清晰吐气时，画面瞬间恢复暖色，汽车才继续前进并从两人旁边擦过。陈小凡护住林雨，两人沿同一动势滚向路边垃圾桶。不得提前恢复，不得撞车，不得让林雨在冻结阶段主动动作。", "吐气前仅暂停嗡鸣；吐气后恢复发动机、气流、翻滚和垃圾桶碰撞声。"),
"S04": ("r2va", False, False, [v3("S04_首帧_V3.png"), chen, boss, office, water],
"办公室深处的量子气泡水回忆", "从Picture 1暖色办公室入场构图开始：赵老板工位固定在办公室最深处、背靠山水画和书柜，员工工位在前中景。陈小凡从前景走向老板，老板拿起量子气泡水喝下；镜头推近瓶中异常气泡，再以短促闪回表现陈小凡意外获得憋气停时能力。老板桌不得移到前景。", "办公室底噪、脚步、瓶盖与吞咽声；异常发生时加入细微能量脉冲。"),
"S05": ("r2va", False, True, [old(5), chen, boss, office],
"办公室首次冻结发现", "暖色正常时间，赵老板在最深处工位将文件递向陈小凡。陈小凡深吸气并闭嘴鼓腮，瞬间切为冷蓝冻结；老板、文件、同事、灯光反射全部定住。Picture 1只作为冻结结果构图目标，不是开场。陈小凡确认世界暂停，不能张嘴。", "办公室声在低频‘咚’后瞬停，只留心跳和暂停嗡鸣。"),
"S06": ("r2va", True, True, [chen, boss, office, props],
"承接冻结办公室，偷换文件", "严格承接上一镜latent的冷蓝冻结状态。陈小凡闭嘴鼓腮走到赵老板深处工位，谨慎抽走老板手中的文件并换入另一份；赵老板和所有同事保持完全僵硬，纸张只有被陈小凡直接接触时才移动，不得自行飘落。结尾陈小凡退到老板桌侧，准备吐气。", "仅有脚步、纸张接触、心跳和暂停嗡鸣。"),
"S07": ("fl2va", True, False, [old(7), chen, boss, office, props],
"吐气恢复，处分变表彰", "严格承接上一镜latent：开场冷蓝冻结，老板仍在最深处工位，陈小凡闭嘴鼓腮站在桌侧。陈小凡吐气后才恢复暖色，老板从冻结姿势自然完成原动作，低头看见被替换的表彰材料，由恼怒转为惊讶并颁给陈小凡。结尾对齐Picture 1的暖色获奖状态。不得把老板桌移到前景。", "吐气前暂停嗡鸣；恢复后办公室声、掌声和喜剧性纸张声自然进入。"),
"S08": ("r2va", False, False, [old(8), chen, transition, props],
"能力投机蒙太奇", "三个短而清楚的暖色喜剧片段：陈小凡在电梯门将关时憋气冻结并钻入；在食堂队伍中冻结后挪到前方；在楼梯上冻结躲过泼洒物。每次都遵守深吸气、闭嘴鼓腮、冷蓝冻结、吐气恢复的顺序；冻结物不得自行移动。", "节奏化环境声，每次冻结都以同一低频‘咚’和瞬时静音标记。"),
"S09": ("r2va", False, True, [v3("S09_首帧_V3.png"), chen, lottery, props],
"发现中奖彩票并产生贪念", "从Picture 1暖色中近景开始：陈小凡空手站在财务桌旁，发现桌面彩票，先惊讶后确认号码，随后露出克制贪念。他拿起彩票又放到彩票机前，深吸气并闭嘴鼓腮，结尾切入冷蓝冻结，为下一镜续接。不要一开场就拿着彩票或得意微笑。", "办公室底噪、纸片拿放和逐渐加重的心跳；结尾‘咚’后静音。"),
"S10": ("fl2va", True, False, [v3("S10_尾关键帧_V3.png"), chen, lottery, props],
"冻结时篡改彩票，恢复后显示无效", "严格承接上一镜latent的冷蓝冻结。陈小凡始终闭嘴鼓腮，在静止的彩票机旁用黑笔篡改票面；只有他接触的手、笔和彩票可以动。完成后吐气，暖色恢复，机器亮起红色错误提示光；他举起污损彩票，表情从期待塌成失望，结尾对齐Picture 1。不得让彩票在冻结中自行飘动。", "冻结段仅笔触、心跳和嗡鸣；恢复后机器错误提示音清楚响起。"),
"S11": ("r2va", False, False, [old(11), chen, training],
"憋气训练蒙太奇", "用近景和特写表现陈小凡在楼梯、室内训练区反复练习憋气：深吸、闭嘴鼓腮、脸逐渐泛红、计时后吐气恢复。动作渐进但不夸张昏厥，不出现墙上时钟或可读数字，保持角色身份与服装一致。", "呼吸、心跳、鞋步和训练器材声构成节奏。"),
"S12": ("r2va", False, True, [old(12), chen, lin, street, car, props],
"再次出现的街头危机", "暖色正常时间，镜头由较宽街景迅速推到中近景。林雨正常走上斑马线，汽车高速逼近且不刹车；陈小凡在路边发现危险，转身冲向她并开始吸气。结尾仍是暖色正常时间，汽车仍在逼近，尚未完成冻结，为下一镜latent保留连续动势。", "高速引擎、脚步、心跳持续增强，没有刹车声。"),
"S13": ("r2va", True, True, [chen, lin, street, car],
"极限时刻冻结并拖离", "严格承接上一镜latent的暖色运动状态。陈小凡完成吸气、闭嘴鼓腮，低频‘咚’后瞬间切为冷蓝冻结；汽车在即将接触前彻底停住。林雨成为僵硬刚体，陈小凡抱住她向路边拖移。汽车和一切背景绝对静止，不能驶过，林雨不能自己走。结尾到达车门附近，陈小凡发现车门锁住。", "‘咚’声后环境骤停，只留用力声、刮擦、心跳和暂停嗡鸣。"),
"S14": ("fl2va", True, True, [v3("S14_尾关键帧_V3.png"), chen, lin, street, car, bins],
"用三只垃圾桶搭成缓冲带", "严格承接上一镜latent的冷蓝冻结和车门锁住状态。陈小凡闭嘴鼓腮，快速将蓝、绿、灰三只带轮垃圾桶逐一推到汽车与林雨之间，错落排成三角缓冲带；只有被他直接推动的桶可以移动，林雨仍是僵硬刚体，汽车绝对不动。结尾对齐Picture 1，三只桶必须完整清楚可见。", "轮子摩擦、急促心跳和暂停嗡鸣；没有交通声。"),
"S15": ("fl2va", True, True, [old(15), chen, lin, street, car, bins],
"恢复时间，汽车撞缓冲桶后安全停下", "严格承接上一镜latent的冷蓝三桶缓冲状态。陈小凡退到林雨身旁后吐气，画面恢复暖色；汽车才继续前进，撞上垃圾桶缓冲带并减速停下，始终不接触人物。陈小凡护住林雨，两人摔坐路边，结尾对齐Picture 1的安全余波。", "吐气后恢复引擎、轮胎与垃圾桶碰撞声，随后落入喘息和短暂耳鸣。"),
"S16": ("fl2va", True, True, [old(16), chen, lin, street],
"余波中林雨靠近，近吻前再度冻结", "严格承接上一镜latent的暖色安全余波。林雨感激地靠近陈小凡，镜头收紧到两人面部；陈小凡误以为她要亲吻，紧张吸气并闭嘴鼓腮。两人嘴唇尚未接触时瞬间切为冷蓝冻结，林雨固定在靠近姿势，结尾对齐Picture 1并保留清晰空气间隙。", "暖色段保留喘息与远处街声；冻结‘咚’后只留心跳和暂停嗡鸣。"),
"S17": ("r2va", True, False, [chen, lin, street],
"承接近吻冻结，恢复后误会打脸", "严格承接上一镜latent的冷蓝近吻姿势和空气间隙。陈小凡面对林雨、闭嘴鼓腮，紧张观察后吐气；暖色恢复，林雨从原姿势自然眨眼、立刻后撤，误会他的靠近，干脆扇他一记耳光后转身离开。只打一次，不重复，不让汽车穿过背景。", "吐气后恢复街声，一记清楚耳光声，随后短暂喜剧静默。"),
"S18": ("r2va", False, False, [v3("S18_首帧_V3.png"), qi, lab, water],
"齐博士进行B型逆向实验", "从Picture 1暖色实验室中近景开始：齐博士观察监视器异常波形，量子气泡水瓶直立在桌上且尚未饮用。他拿起瓶子进行受控实验，监视器出现反向变化；他以可理解的中文说话，但语序和节奏略显倒置古怪，不使用真正倒放到无法听懂的音频。镜头最后推近他恍然大悟的脸。", "实验室设备低鸣、瓶盖声和轻微电子反向脉冲；对白必须清晰可懂。")
}

AUDIO = {
    "S01": "男性内心旁白（S1）只说一次：<d>[Chinese] 三天前，我还只是个连全勤奖都保不住的废物。</d> 这是画外音；陈小凡始终闭嘴鼓腮，任何人物都不做口型。除这句外无其他对白、旁白或人声。",
    "S02": "男性内心旁白（S1）只说一次：<d>[Chinese] 能力很强……就是有点缺氧。</d> 这是画外音；陈小凡始终闭嘴鼓腮，林雨完全静止，二人都不做口型。除这句外无其他对白、旁白或人声。",
    "S03": "时间恢复且两人停稳后，林雨（S2）只说一次：<d>[Chinese] 你救了我？</d> 只有林雨做准确中文口型。陈小凡不说话，只竖起大拇指。",
    "S04": "赵老板（S3）只说一次：<d>[Chinese] 陈小凡！你又迟到！</d> 只有赵老板做准确中文口型；陈小凡无对白。",
    "S05": "本镜无对白、无旁白、无可辨识人声；人物不得说话或做说话口型。",
    "S06": "男性内心旁白（S1）只说一次：<d>[Chinese] 这能力……有点不讲劳动法啊。</d> 这是画外音；陈小凡闭嘴鼓腮，不做口型。除这句外无其他人声。",
    "S07": "时间恢复后，赵老板（S3）只说一次：<d>[Chinese] 鉴于陈小凡表现优秀……</d> 只有赵老板做准确中文口型；陈小凡和背景同事无台词。",
    "S08": "本镜无对白、无旁白、无可辨识人声；所有人物不得做说话口型。",
    "S09": "暖色正常时间中，陈小凡（S1）只说一次：<d>[Chinese] 终于轮到我逆袭了。</d> 只有这句话需要准确中文口型；结尾吸气后闭嘴，不再说话。",
    "S10": "时间恢复后，彩票机电子女声（S4）只播报一次：<d>[Chinese] 无效票。无法识别。</d> 声音来自机器；陈小凡全程无对白、不做口型。",
    "S11": "最后一个训练片段中，小朋友（S5）只说一次：<d>[Chinese] 叔叔，这里水深五十厘米。</d> 只有小朋友做准确中文口型；陈小凡无对白。",
    "S12": "手机系统女声（S4）只播报一次：<d>[Chinese] 个人纪录：十四点二秒。</d> 声音来自手机；陈小凡和林雨无对白、不做说话口型。",
    "S13": "本镜无对白、无旁白；陈小凡只能发出不成词的短促鼻音和用力呼吸，不得形成任何可辨识词语。",
    "S14": "本镜无对白、无旁白；陈小凡只能有闭口用力鼻音，不得形成任何可辨识词语。",
    "S15": "时间恢复并确认安全后，林雨（S2）说：<d>[Chinese] 你是超人吗？</d> 随后陈小凡（S1）说：<d>[Chinese] 不，我只是……比较能憋。</d> 两句依次出现，各自只说一次，分别由对应人物做准确中文口型。",
    "S16": "男性内心旁白（S1）只说一次：<d>[Chinese] 等等，这时候暂停是不是有病？</d> 这是画外音；陈小凡闭嘴鼓腮，林雨冻结，二人都不做口型。",
    "S17": "耳光之后，陈小凡（S1）只说一次：<d>[Chinese] 不是，你听我解释！</d> 只有陈小凡做准确中文口型；林雨无台词。",
    "S18": "齐博士（S6）只说一次：<d>[Chinese] 看来，B型也成功了。</d> 中文必须清晰可懂，采用略显倒置、停顿古怪的语气，不得真正倒放音频，不得生成第二句或乱码人声。",
}

def prompt_for(shot_id, refs, summary, detail, sound):
    defs = []
    for i, ref in enumerate(refs, 1):
        name = Path(ref).stem
        defs.append(f"<Picture {i}>是参考资产“{name}”，仅锁定其中相关角色、场景、道具或关键状态。")
    return f"""subject_definitions:
{chr(10).join(defs)}

summary:
[reference generation] {summary}。9:16竖屏，电影感半写实3D动画，优先中近景和清晰面部。

retention_analysis:
严格锁定参考角色身份、脸型、发型、体态和服装；锁定场景轴线、道具外形与关键空间关系。latent续镜必须从上一镜最终状态无跳变开始；关键帧只控制指定开场或结尾，不擅自改写时间状态。

detailed_description:
[Shot 1] {detail}
全程避免远景小脸、身份漂移、额外人物、可读文字、字幕、数字、Logo、车牌和水印。时间冻结时，除陈小凡及被他直接接触推动的对象外，一切人物、车辆、衣发、反射、灰尘和松散物必须绝对静止。音频严格执行以下唯一语言规则：{AUDIO[shot_id]}

overall_soundscape:
{sound}

non_diegetic_music:
低音量电影氛围配乐，只服务紧张与喜剧节奏，不覆盖对白和关键音效。"""

board = json.loads(BOARD.read_text(encoding="utf-8-sig"))
backup = BOARD.with_name(f"storyboard_before_v3_{datetime.now():%Y%m%d_%H%M%S}.json")
backup.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")

for shot in board["shots"]:
    mode, cont, save, refs, summary, detail, sound = specs[shot["id"]]
    shot["generation_mode"] = mode
    shot["continue_from_previous"] = cont
    shot["save_latent"] = save
    shot["references"] = refs
    shot["prompt"] = prompt_for(shot["id"], refs, summary, detail, sound)
    # Prompt/reference/latent settings changed for every shot. Keep historical
    # result records, but require a fresh run so the new latent chain is real.
    shot["status"] = "draft"
    shot["error"] = ""

BOARD.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
DOCS.mkdir(parents=True, exist_ok=True)
audit_json = DOCS / "憋住世界就停了_18镜头_V3_latent关键帧审核版.json"
audit_json.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")

lines = ["# 憋住世界就停了｜18镜头 V3 Latent + 关键帧审核版", ""]
for shot in board["shots"]:
    lines += [f"## {shot['id']}｜{shot['title']}", "", f"- 模式：{shot['generation_mode'].upper()}", f"- 承接上一镜 latent：{'是' if shot['continue_from_previous'] else '否'}", f"- 保存 latent：{'是' if shot['save_latent'] else '否'}", "", shot["prompt"], ""]
(DOCS / "憋住世界就停了_18镜头_V3_latent关键帧审核版_中文提示词.md").write_text("\n".join(lines), encoding="utf-8")
print(backup)
print(audit_json)
