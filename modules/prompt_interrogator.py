"""Image-to-prompt helpers backed by the local ComfyUI interrogation workflow."""

from __future__ import annotations

import copy
import ast
import json
import difflib
import os
import re
import time
import uuid
from typing import Any, Callable

from modules.prompt_optimizer import parse_prompt_optimizer_output
from modules import prompt_optimizer as _prompt_optimizer
from modules.image_reverse_skill import (
    REQUIRED_EVIDENCE_KEYS,
    REVERSE_PROMPT_SKILL_GUIDE,
    VISUAL_EVIDENCE_GUIDE,
    validate_reverse_prompt_quality,
)
from modules.llm_client import DIRECT_FINAL_SYSTEM_PROMPT, chat_text, image_to_data_url, llm_provider_name


INTERROGATE_MAX_IMAGE_SIDE = 1280
INTERROGATE_MAX_IMAGE_PIXELS = 1_600_000

CAR_FRONT_SEAT_POSE_STANDARD = (
    "车内前排人物姿态标准样例：亚洲女性外貌倾向，偏白皙暖调肤色，黑色长直发和齐刘海，"
    "白色贴身短袖衬衫，深红色百褶短裙，黑色过膝丝袜；人物跪坐在车厢前排座椅上，"
    "面部朝向镜头，躯干转向座椅靠背方向；一侧手臂向座椅靠背方向延伸到画面边缘，"
    "另一只手搭在前景座椅靠背顶部；膝盖和小腿支撑在座椅坐垫区域，黑色过膝丝袜覆盖腿部；"
    "画面右侧可见方向盘和车门区域，但不能写手搭方向盘；车窗外是明亮绿色草地/植被。"
)

BEDROOM_SEATED_POSE_STANDARD = (
    "卧室床上坐姿标准样例：年轻东亚女性外貌倾向，白皙暖调肤色，深棕或黑棕长直发，齐刘海；"
    "人物坐在床铺上，躯干正对镜头略微前倾，画面左侧手臂向镜头前方抬起，前景手部因运动或焦外呈模糊，"
    "画面右侧手臂下垂靠近床面；低领吊带上衣可见蕾丝边、锁骨、上胸和乳沟，外搭浅色开衫，"
    "下装为浅色抽绳短裤，腿部可见至膝部/长筒袜区域；底部若有短视频 UI、水印、关注按钮，需写入细节与文字或负面规避，"
    "不得写双臂自然垂落、裁切到大腿中部、adult_nudity 或裸露乳头。"
)

QWEN_IMAGE_INTERROGATE_TEMPLATE = (
    "你是图片反推提示词助手，按 GPT Image / Nano Banana 类图像模型更容易执行的结构化描述方式工作。"
    "你的目标不是写一句概括或标签列表，而是先完整观察画面，再生成适合文生图/图生图复刻画面的高密度提示词。"
    "核心原则：描述场景，不要只堆关键词；每个结论都必须来自图中清晰可见的像素事实。"
    "必须只输出一个有效 JSON 对象，不要 markdown，不要解释，不要省略必填键。"
    "JSON 必须包含以下四个顶层键：keyword_prompt, english_prompt, structured_prompt, structured_prompt_en。"
    "格式示例："
    '{"keyword_prompt":"中文纯词汇提示词","english_prompt":"English plain keyword prompt",'
    '"structured_prompt":{"subject":"...","subject_attributes":"...","action":"...","pose_details":"...",'
    '"hand_details":"...","foot_details":"...","joint_body_mechanics":"...","facial_expression_details":"...",'
    '"occlusion_crop_details":"...",'
    '"exposed_body_details":"...","intimate_body_details":"...","sexual_act_details":"...",'
    '"genital_details":"...","fluid_contact_details":"...","nsfw_content_details":"...","content_safety_labels":[],'
    '"scene":"...",'
    '"foreground":"...","midground":"...","background":"...",'
    '"composition":"...","camera_lens":"...","lighting":"...","style":"...","color_palette":"...",'
    '"mood_atmosphere":"...","materials_textures":[],"clothing_accessories":[],'
    '"environment_objects":[],"important_details":[],"visible_text":[],"quality_notes":[],"constraints":[]},'
    '"structured_prompt_en":{"subject":"...","subject_attributes":"...","action":"...","pose_details":"...",'
    '"hand_details":"...","foot_details":"...","joint_body_mechanics":"...","facial_expression_details":"...",'
    '"occlusion_crop_details":"...",'
    '"exposed_body_details":"...","intimate_body_details":"...","sexual_act_details":"...",'
    '"genital_details":"...","fluid_contact_details":"...","nsfw_content_details":"...","content_safety_labels":[],'
    '"scene":"...",'
    '"foreground":"...","midground":"...","background":"...",'
    '"composition":"...","camera_lens":"...","lighting":"...","style":"...","color_palette":"...",'
    '"mood_atmosphere":"...","materials_textures":[],"clothing_accessories":[],'
    '"environment_objects":[],"important_details":[],"visible_text":[],"quality_notes":[],"constraints":[]}}。'
    "硬性要求：keyword_prompt 必须是中文；english_prompt 必须是英文；"
    "structured_prompt 必须是中文 JSON；structured_prompt_en 必须是英文 JSON，二者字段含义一致；"
    "keyword_prompt 和 english_prompt 必须是连贯的高密度场景描述短段落，可以用逗号分隔，但不能退化成孤立标签；"
    "二者都要覆盖主体身份/年龄感、可见人种或外貌倾向、肤色、面部表情、发型发色、身体可见范围、动作姿态、手部位置、服装版型、服装材质纹理、"
    "前景、中景、背景、构图、镜头角度、拍摄距离、光线方向、颜色、氛围和风格；"
    "必须按空间扫描顺序补足细节：先画面外围再中心，先上方再下方，先画面左侧再右侧，分别描述左上角、右上角、左下角、右下角、前景、中景、背景出现的可见物体、边界和遮挡关系；"
    "两个 structured 对象只保留图中清晰可见的视觉信息，省略未知、空字符串和空数组；"
    "人物 subject_attributes 必须写清可见外貌特征、肤色和年龄感；人种/族裔只作为可见外貌倾向用于复刻，不能断言真实身份，看不准就省略；"
    "人物动作和姿势必须拆解到 pose_details：写清站/坐/躺/蹲/跪、身体朝向、头颈角度、肩膀、腰胯、手臂、手指、腿部、脚部的位置和受力关系；"
    "坐姿不能只写“坐在xxx”，必须分类为正坐、侧坐、半跪坐、跪坐、蹲坐、盘腿坐、跨坐、倚坐、斜坐等可见姿态，并写清臀部/大腿/膝盖/脚掌的支撑点；"
    f"{CAR_FRONT_SEAT_POSE_STANDARD}"
    "车内座椅姿态若人物膝盖/小腿支撑在座椅坐垫上，必须优先写成“人物跪坐在车厢前排座椅上，面部朝向镜头，躯干转向座椅靠背方向”这类可复刻结构，不要退化成“坐姿”；"
    "手部必须写清每只手的位置、手指弯曲/张开/握持/遮挡、是否接触身体或物体，放入 hand_details；"
    "脚部只有进入画面时才写脚尖方向、足跟/脚掌是否着地、双脚间距和承重关系，放入 foot_details；"
    "腿部和不完整展示区域必须写清可见起止边界，例如“画面裁切到大腿中段/膝上/小腿下方”，不要把未进入画面的身体部位当成关键词补进正向提示词；"
    "裁切边界必须按实际画面结束位置写；如果只看到头部到大腿/膝上/膝盖区域，绝不能写“全身、脚踝、脚部可见”；"
    "occlusion_crop_details 只写可见裁切线和可见遮挡物，例如“画面底部裁切在膝部区域”“衣物边缘覆盖大腿内侧”，不要列出画外身体部位名称；"
    "不可见内容直接省略，不要把不可见脚写成“脚部细节不清晰”，不要把被遮挡隐私部位写成可见；"
    "不要把字段填成笼统的“不可见/无/不清晰”；如果没有具体遮挡对象和裁切位置，就省略该字段；"
    "关节和肢体受力必须写入 joint_body_mechanics：肩、肘、腕、腰胯、膝、踝的弯曲角度、受力、重心和身体轴线；"
    "脸部细节和表情必须写入 facial_expression_details：眼神方向、眉眼状态、嘴唇开合、牙齿/舌头是否可见、面部肌肉紧张或放松；"
    "如图中存在暴露皮肤、裸露身体、内衣泳装、透视/低领/露肩/露背/高开衩等情况，必须写入 exposed_body_details，"
    "明确可见身体部位、暴露程度、衣物覆盖关系，并区分“泳装/内衣/局部裸露/完全裸露”；看不清时省略具体类型，不要进入正向提示词；"
    "如果图中存在明确成人/NSFW/裸露/性化可见内容，必须额外写入 nsfw_content_details，"
    "当确认是成年裸露内容时，content_safety_labels 至少包含 NSFW 和 adult_nudity；"
    "成年裸露中可见隐私部位时必须写入 intimate_body_details，具体描述可见乳头、乳晕、外阴/阴茎/睾丸、臀沟、肛门等部位、遮挡关系和可见程度；"
    "不能只写是否存在性行为；只要图中有具有性意味的可见内容，就必须分别写入 genital_details、sexual_act_details、fluid_contact_details；"
    "genital_details 写清可见性器官的具体部位、颜色/红肿/张开/遮挡等可见状态；"
    "sexual_act_details 写清插入、摩擦、接触、自慰、口交、性交、手指进入、性玩具接触等可见动作，以及使用的身体部位或物体；"
    "fluid_contact_details 写清液体、分泌物、白色液体、湿润反光、沾附位置和接触对象；"
    "用实事求是、具体、可复刻的语言描述可见的 NSFW 类型、可见解剖部位、衣物遮挡关系、是否存在性行为或互动；"
    "nsfw_content_details 只写可见事实，不写氛围、吸引力或审美评价，禁止用“尺度较大、性感、诱人、青春可爱”等主观词替代具体可见事实；"
    "不要加入不可见的性行为、液体、道具或接触；"
    "如果主体年龄不明确，只描述非性化可见事实和年龄不确定性，不写性化 NSFW 细节；"
    "important_details 需要尽量列出 14 到 30 条可见细节，覆盖人物/主体局部、五官、发丝走向、手臂手指、服饰配件、"
    "服装领口/袖型/长度/贴合度、暴露皮肤边界、道具、背景物体、材质纹理、光影、画面边缘小物件、可读文字；"
    "foreground、midground、background 要分别描述画面不同空间层次，不要只描述主体；"
    "画面区域描述必须从大范围到细节逐层收窄：外圈环境/车窗/墙面/地面/座椅/道具，再到人物整体，再到头发、脸部、手臂、手指、腰胯、腿部、服装边缘和材质；"
    "方向和相对位置必须以画面坐标描述：画面左/右/上/下、前景/中景/背景、人物左/右侧、镜头近端/远端；"
    "“前/后/左/右/向前”不是绝对方向，必须注明参照系：相对画面、相对镜头、相对人物身体、相对座椅靠背/方向盘/车窗等物体；"
    "不要删除没有参照物的动作信息，而是补充参照物和端点：把“手臂向前伸展/身体朝前”细化为“手臂向画面左侧伸展”“手臂向座椅靠背方向延伸到画面边缘”“面部朝镜头，躯干朝座椅靠背”；"
    "物体关系必须写清是否真实接触、遮挡或仅相邻；不能因为场景常识自动补全动作，例如车内有方向盘不等于手搭方向盘。"
    "车内场景必须按可见部件命名：车厢前排、驾驶舱内部、驾驶座、副驾驶座、后排座椅只能在座位和方向盘关系明确时使用；不明确时写“车厢前排区域”。"
    "窗外绿色背景只能写草地/植被/路边绿地等可见事实；只有看到农作物行列、田埂或农田结构时，才可写田野/农田。"
    "composition 必须写清画幅边界与主体占比，例如全身、膝上、半身、胸像、特写、正面居中、留白比例、裁切到哪里；"
    "camera_lens 必须写清机位角度、拍摄距离、视角和景深，例如轻微俯视、平视、中景、全身人像、浅景深；"
    "如果画面是手机近距离、低角度、仰拍、抬腿靠近镜头、腿部/手部因近大远小强烈变形，必须写清近距离透视和前景肢体占比；"
    "不要把明显低角度仰拍或极近距离透视写成平视；"
    "如果人物从头部到腿部大范围可见，绝不能写成特写；如果背景只是纯色墙面/无缝影棚/渐变背景，不要笼统写室内；"
    "如果服装是连衣裙、吊带、抹胸、针织、丝绸、制服、机甲等，必须写出可见版型、肩部/领口结构、长度、贴合度和材质纹理；"
    "袜类必须拆分“长度款式”和“材质透明度”：过膝袜/长筒袜/大腿袜描述袜口位置和长度，丝袜/连裤袜描述尼龙感、半透明度、细密网纹和光泽；二者不能互相替代；"
    "如果长度和材质都可见，必须合成为复合词，例如“黑色过膝丝袜/黑色大腿丝袜”，不要拆成黑色过膝袜或黑色丝袜二选一；"
    "衣物类型只能按可见结构判断；看不到肩带不要写吊带，看不到裤脚/裙摆完整结构时只写可见衣物边界和遮挡关系，不要写“短裙或短裤疑似”这类二选一；"
    "style 不要泛写自然/柔和，要说明是写实摄影、棚拍人像、手机感照片、3D 渲染、插画、动漫、电影剧照等可见风格；"
    "quality_notes 写可复刻的画质信息，例如柔焦、皮肤高光、低对比、背景虚化、细节锐度、AI 生成感或照片感；"
    "constraints 写复刻时应避免的错误，例如不要裁成头像特写、不要新增道具、不要改变背景颜色、不要省略衣物纹理；"
    "不要加入图中没有的人物、翅膀、文字、品牌或物体；不要重复整段 keyword_prompt；"
    "如果某个细节看不清，直接省略，不要把“疑似/可能/隐约”写进最终正向提示词。"
)

FAST_IMAGE_INTERROGATE_TEMPLATE = (
    "你是快速图片反推助手。目标是在 30 秒内输出可直接用于复刻画面的紧凑 JSON。"
    "标准反推定位：快速、准确、可用，输出可复用的高密度描述，但不追求逐像素或 1:1 级别复刻规格。"
    "必须只输出一个有效 JSON 对象，不要 markdown，不要解释。"
    "顶层键固定为 keyword_prompt, english_prompt, structured_prompt。"
    "structured_prompt 必须是中文分组对象，格式为："
    '{"画面描述":{"主体":"","动作姿态":"","手脚关节":"","表情脸部":"","服装妆容":"",'
    '"裸露与NSFW":"","场景背景":"","构图镜头":"","光影颜色":"","材质细节":""},'
    '"负面提示词":{"人物错误":[],"构图错误":[],"服装错误":[],"背景错误":[],"NSFW误判":[],"质量错误":[]}}。'
    "JSON 必须结构化排列：画面描述只能放正向可见事实；负面提示词只能放要规避的纯短语/标签；"
    "不要把正向描述和负面约束混在同一个字符串里，不要在 keyword_prompt 里写不要/避免/无明显。"
    "画面描述禁止使用不绝对的二选一和猜测词，例如“并拢或轻微分开、短裙或短裤、可能、疑似、不确定、无法确认”；判断不了就省略该状态，只写可见裁切、遮挡和支撑关系。"
    "负面提示词字段禁止写自然语言命令，不能出现“不要、避免、禁止、no、avoid、do not”；"
    "例如要规避露出脸部就写“脸部”，要规避双腿交叉就写“双腿交叉”，要规避水印就写“水印/watermark”。"
    "按图像模型用词组织：Qwen Image 可使用正向短句加负面标签；FLUX.2 和 Z-Image Turbo 更依赖正向描述，负面只作为通用规避集合。"
    "keyword_prompt 写一段中文高密度正面提示词，english_prompt 写对应英文提示词。"
    "必须覆盖可见主体、年龄感或年龄不确定性、可见外貌倾向、肤色、动作姿态、手脚关节、表情脸部、服装材质、背景、构图、光影、颜色、画质。"
    "必须按画面区域补足信息：从画面外围到中心，从左上/右上/左下/右下到主体局部，写清每个区域的可见物体、人物方向、遮挡和裁切边界。"
    "坐姿必须细分，不得只写“坐在xxx”：要写正坐/侧坐/半跪坐/跪坐/蹲坐/盘腿坐/跨坐/倚坐/斜坐，以及可见支撑点。"
    f"{CAR_FRONT_SEAT_POSE_STANDARD}"
    "车内座椅上膝盖/小腿支撑时，动作姿态应写“人物跪坐在车厢前排座椅上，面部朝向镜头，躯干转向座椅靠背方向”这类完整姿态句。"
    "如果存在成人裸露、性器官、性意味接触或液体，必须在 裸露与NSFW 中实事求是写可见事实和 NSFW/adult_nudity 标签；"
    "如果年龄不明确，只描述非性化可见事实和年龄不确定，不写性化细节。"
    "腿部和不完整展示区域必须写清可见起止边界，例如画面裁切在大腿/膝盖/小腿哪个区域。"
    "裁切边界必须按实际画面结束位置写；只看到头部到大腿/膝上/膝盖区域时，绝不能写“全身、脚踝、脚部可见”。"
    "没看到的身体部位不要提及名称；只描述可见的画幅边界、可见衣物、可见肢体和可见遮挡物。"
    "例如不要写“双脚不可见/隐私部位不可见”，应写“画面边缘裁切在腿部区域”或“衣物与大腿形成遮挡边界”。"
    "方向和物体相对位置必须按画面坐标写清楚：画面左/右、前景/背景、人物左/右侧、镜头近端/远端；"
    "前/后/左/右/向前必须带参照物；不要删除动作信息，应把无参照的“手臂向前伸展”补写成向画面左侧、向镜头、向座椅靠背、向人物身体前方等可见方向。"
    "必须确认手、脚、身体和物体是否真实接触，不得因为场景物件存在就补写动作，例如车内有方向盘不等于手搭方向盘。"
    "车内位置和窗外场景不得过度确定：座位关系不明确写“车厢前排区域”，绿色窗外只写草地/植被，不要自动写田野/农田。"
    "负面提示词不要写命令句；如需防止模型补全不可见内容，写“多余肢体补全、额外身体细节”等纯短语。"
    "正向提示词和画面描述只能写看见了什么，禁止写“无明显、没有明显、未见、无可见、局部暴露、部分暴露、尺度较大、性感、诱人”等含糊判断；"
    "缺失/否定/不可确认内容放入负面提示词或直接省略；可见裸露必须写具体部位和衣物遮挡边界。"
    "负面提示词只写规避短语，不要和画面描述重复。"
    "严格控制长度：keyword_prompt 不超过 180 个汉字，english_prompt 不超过 90 个英文词，"
    "画面描述每个字段不超过 45 个汉字，负面提示词每组最多 2 条；整体不超过 520 tokens。"
    "避免长篇解释，避免重复句。"
)

IMAGE_INTERROGATE_EXPERTS: tuple[dict[str, str], ...] = (
    {
        "id": "composition",
        "label": "构图镜头专家",
        "instruction": "只分析画幅、主体占比、裁切边界、前景/中景/背景、机位角度、拍摄距离、透视变形和景深范围。"
        "必须按区域扫描画面：外圈到中心、左上/右上/左下/右下、左侧到右侧、前景到背景，逐项记录可见物体和遮挡边界。"
        "明确低角度、仰拍、近距离、肢体靠近镜头、不完整展示区域和裁切线位置，不要分析服装审美或性内容；"
        "裁切边界必须精确到画面实际结束处；如果脚踝或脚没有进入画面，不能写包含脚踝或全身。"
        "必须用画面坐标写清物体相对位置：画面左/右/上/下、前景/中景/背景、镜头近端/远端；"
        "车内位置只能按可见部件判断，座位关系不明确时写车厢前排区域；窗外绿色不能自动写成田野/农田。"
        "镜头焦段、光圈、快门、ISO 等参数交给摄影参数专家，不要在本专家里编造具体数值。",
    },
    {
        "id": "photography_parameters",
        "label": "摄影参数专家",
        "instruction": "只分析可由画面视觉特征判断的摄影设备和曝光参考参数：镜头类型/等效焦段、参考光圈、参考快门、参考 ISO、"
        "曝光补偿、采光度、动态范围、白平衡、传感器/手机感/相机感、压缩锐化痕迹。"
        "可以写一个明确的生图参考参数组合，例如“参考参数：35mm 等效焦段，f/2.8，1/125s，ISO 400，自动白平衡，浅景深”；"
        "这些参数服务于生图复刻，不代表真实 EXIF。不要写“推断、估计、可能是参数”等分析词。"
        "光圈术语必须准确：f/1.4-f/4 属于大光圈或中大光圈，f/5.6 左右属于中等光圈，f/8-f/16 才是小光圈；"
        "不得把 f/2.8-f/4.0 描述为小光圈。",
    },
    {
        "id": "color_light",
        "label": "颜色光影专家",
        "instruction": "只分析主色、辅色、肤色/服装色、背景色、光源方向、阴影、高光、曝光、对比度、柔焦和景深对色彩的影响。"
        "颜色必须精准：尽量写具体颜色名和近似 HEX 色值，例如“浅樱粉 #F6C9D6、冷白 #F4F6F8、墨黑 #111827”；"
        "不要只写“粉色/粉色系/蓝色系/暖色系/冷色系”，必须落到具体色相、明度、饱和度，并绑定具体对象。"
        "必须写色温或冷暖参考，例如“暖白光 3200K-4000K、自然日光 5000K-5600K、冷白光 6500K”，不要只写光线柔和。",
    },
    {
        "id": "mood_style",
        "label": "氛围风格专家",
        "instruction": "只分析照片/手机感/棚拍/AI生成感/写实风格、空间氛围和情绪基调。禁止用空泛夸赞替代可见事实。",
    },
    {
        "id": "body_pose",
        "label": "肢体动作专家",
        "instruction": "只分析头颈、肩、肘、腕、手、手指、腰胯、腿、膝、踝、脚、重心、身体轴线、关节屈伸和肢体遮挡。"
        "fields 必须拆成整体姿态、支撑点、身体朝向、手臂端点、腿部边界、接触遮挡六类，不要只给一个笼统 pose summary。"
        "必须写清人物身体朝向、左右肢体方向、腿部可见起止边界、画面裁切到哪个身体区域，以及手脚是否真实接触身体或物体。"
        "方向词必须有参照系：画面坐标、镜头方向、人物身体坐标或物体坐标；不要删除无参照动作，要把“手臂向前伸展/身体朝前”补充为带画面方向、物体端点和裁切边界的描述。"
        "例如可写“面部朝镜头，躯干朝座椅靠背，手臂向座椅靠背方向延伸到画面边缘”。"
        "如果是坐姿，必须进一步判定正坐、侧坐、半跪坐、跪坐、蹲坐、盘腿坐、跨坐、倚坐或斜坐，并写清臀部/大腿/膝盖/脚掌分别由什么支撑。"
        "如果是海边/地面上的蹲姿，双脚或鞋底落地承重、膝盖屈曲靠近身体时，写“人物下蹲/蹲姿，鞋底踩在地面承重”；"
        "禁止写“半蹲坐姿 (Half-crouching Sit)”“双膝和小腿接触于岩石表面”“膝盖支撑在岩石上”，除非膝盖或小腿真实压在地面并清晰可见。"
        "鞋子覆盖脚踝或脚踝被画面/鞋口遮挡时，不得写“小腿和脚踝区域被丝袜包裹”；只能写可见小腿/膝上腿部被黑色过膝丝袜覆盖，鞋口处形成遮挡。"
        "手部端点必须按画面坐标写，例如“画面右侧手臂弯曲抬起，手靠近画面右侧太阳穴/发丝”；"
        "不要强行写人物左手/右手或“头部左上方发梢”，除非左右身份和接触点清晰可见。"
        f"{CAR_FRONT_SEAT_POSE_STANDARD}"
        "车内座椅姿态要区分正坐、侧坐、跪坐、半跪坐；膝盖/小腿/脚掌支撑在座垫上时应写跪坐或半跪坐，不要泛写坐姿。"
        "类似车内前排座椅画面应优先输出“人物跪坐在车厢前排座椅上，面部朝向镜头，躯干转向座椅靠背方向”这种整体姿态结构。"
        "若画面显示人物面部朝镜头但躯干朝座椅靠背，应明确写“面部朝向镜头”和“躯干转向座椅靠背方向”两个独立事实。"
        "若一侧手臂越过座椅靠背并到达画面边缘，应写“手臂向座椅靠背方向延伸到画面边缘”，不要误写成手搭方向盘。"
        "禁止写“双腿并拢或轻微分开”这类二选一模糊句；必须选择可见状态，或把遮挡导致无法判定写入 uncertain。"
        "如果只看到大腿或膝上区域，不能写脚踝、脚掌、全身姿态。"
        "不可见部位不要作为正向关键词补写；只写可见裁切线、遮挡物和可见肢体。"
        "场景物件不能自动绑定动作，例如方向盘在画面中不代表手搭方向盘，座椅在前景不代表人物握住座椅，必须按可见接触关系判断。",
    },
    {
        "id": "expression_language",
        "label": "表情语言专家",
        "instruction": "只分析脸部可见范围、头部朝向、视线方向、表情张力、五官细节和脸部妆造。"
        "必须写人物可见外貌倾向、肤色和脸部肤质；人种/族裔只能作为外貌复刻倾向，不要断言真实身份。"
        "必须尽量拆解眼睛/眼睑/瞳孔高光/眼线眼影、眉形眉色、鼻梁鼻翼、脸颊轮廓、嘴唇开合/唇形/唇色/唇妆、"
        "牙齿或舌头是否可见、下颌线、发际线、刘海和碎发遮挡、腮红/底妆/高光/阴影/睫毛等可见妆造。"
        "微笑、嘴角上扬、张嘴、露齿必须有清楚可见的嘴角或牙齿依据；嘴唇闭合且嘴角不明显时写平静闭唇，不要写嘴角微扬。"
        "脸部被裁切或模糊时必须明确具体裁切或模糊区域，不要补写看不见的五官和妆容。",
    },
    {
        "id": "sexual_boundary",
        "label": "性内容边界专家",
        "instruction": "只分析可见裸露、隐私部位、性器官、性行为、性意味接触、液体/分泌物、衣物遮挡关系和年龄不确定性。"
        "只写可见事实；如果年龄不明确，只描述非性化可见事实和年龄不确定，不写性化细节。"
        "若确认成人裸露或明确性内容，必须给出 NSFW/adult_nudity/explicit_sexual_content 等标签。",
    },
    {
        "id": "clothing_makeup",
        "label": "服装妆容专家",
        "instruction": "只分析服装版型、领口、袖型、肩部结构、裙/裤边界、贴合度、配饰、发型和妆容。"
        "必须重点识别并描述可见的袜子、短袜、长袜、过膝袜、长筒袜、大腿袜、连裤袜、丝袜、吊带袜、内衣、胸罩、文胸、内裤、泳装、打底裤等局部服饰；"
        "袜类必须拆成长度款式和材质本质两层：过膝袜/长筒袜/大腿袜写袜口位置、覆盖到大腿或膝上；丝袜/连裤袜写尼龙感、半透明、细网纹、光泽、贴肤度；"
        "当长度和材质都可见时使用复合词，例如黑色过膝丝袜、黑色大腿丝袜、黑色连裤丝袜；"
        "不能把黑色过膝袜直接等同于黑色丝袜，也不能把半透明丝袜写成普通黑色棉袜或裸腿；"
        "写清款式、长度、腰头/袜口/肩带/罩杯/钢圈/蕾丝/缝线/花边/蝴蝶结/透明度/光泽/贴合度/褶皱/遮挡边界。"
        "衣物类型必须来自可见结构；看不到肩带不要写吊带，看不到完整裙摆/裤脚时省略具体款式；"
        "不要把丝袜误写成裸腿，不要把内衣误写成普通上衣，不要把短裤/短裙/内裤强行互相替换。",
    },
    {
        "id": "materials_texture",
        "label": "材质纹理专家",
        "instruction": "只分析皮肤质感、布料材质、褶皱、缝线、反光、透光、粗糙度、光泽度、织法、纹理密度、颗粒度、锐度、"
        "墙面、地面、门框、背景物件等可复刻材质纹理。必须写清材质细节颗粒度，例如“缎面细密高光、透明丝袜细网纹、皮肤低颗粒平滑质感、墙面哑光细颗粒”。",
    },
)

EXPERT_ID_LIST_TEXT = ",".join(spec["id"] for spec in IMAGE_INTERROGATE_EXPERTS)

GLOBAL_EXPERT_OVERVIEW_TEMPLATE = (
    "你是图片反推专家组的全局概览调度器。先粗看整张图，只决定需要哪些专家，不输出最终提示词。"
    "必须统一使用中文，只输出有效 JSON，不要 markdown。"
    "输出格式："
    '{"has_person":true,"image_type":"人像/物体/场景/产品/建筑/其他",'
    '"visible_elements":["主体","环境","关键物件"],'
    '"recommended_experts":["composition"],"reason":"一句话说明"}。'
    f"recommended_experts 只能从这些 id 中选择：{EXPERT_ID_LIST_TEXT}。"
    "如果图中有人物，必须选择全部人物相关专家：composition,photography_parameters,color_light,mood_style,body_pose,expression_language,sexual_boundary,clothing_makeup,materials_texture。"
    "如果没有人物，按主体选择构图、摄影、颜色、氛围、材质、服饰/产品外观等必要专家，不要选择人物姿态和表情专家。"
    "visible_elements 只列可见大类，不要猜画外内容。"
)

EXPERT_IMAGE_INTERROGATE_TEMPLATE = (
    "你是图片反推专家组成员。专家代号: {expert_id}；专家名称: {expert_label}。"
    "你的任务不是输出最终提示词，而是从自己的专业维度识别可见事实。"
    "专业范围: {expert_instruction}"
    "必须统一使用中文输出；只能输出自己专业边界内的观点，不能替其他专家做结论。"
    "本专家全部观点合计约 100 个汉字，超出会被系统裁剪。"
    "必须只输出一个有效 JSON 对象，不要 markdown，不要解释。"
    "JSON 格式: "
    '{"id":"{expert_id}","label":"{expert_label}","summary":"一句话结论",'
    '"fields":{{"相关字段":"高密度事实描述"}},"observations":["可见事实1","可见事实2"],'
    '"uncertain":["内部备注，不进入正向提示词"],"negative_constraints":["误判短语"],"confidence":0.0}。'
    "只写图中可见像素事实；禁止写高度可信、推断、疑似、可能、看起来像、应当是、无法确认、不可见、画面外、被裁切的身体部位名称。"
    "看不到的内容不要写进 summary、fields 或 observations；如果必须记录风险，只能写入 uncertain，且最终合并不会作为正向提示词。"
    "不要补全未进入画面的内容，不要写泛化空值如“无/不可见/不清晰”，不要因为场景常识绑定人物动作。"
)

EXPERT_IMAGE_REVIEW_TEMPLATE = (
    "你是图片反推专家组的评审专家。你的任务是复核各领域专家是否足够细腻、是否只写了图中可验证事实、"
    "是否存在跨领域越权、空泛描述、画外补全、方向/裁切/服装/NSFW 误判。"
    "必须结合原图复核，不要只看文字自洽。必须统一使用中文，只输出有效 JSON，不要 markdown。"
    "评分标准：detail_score 判断颗粒度，factual_score 判断图像事实一致性，boundary_score 判断是否在专家职责范围内。"
    "低于 0.72 或存在 unsupported 事实时 passed=false，并给 retry_instruction。"
    "输出格式："
    '{"summary":"整体评审结论","retry_expert_ids":["composition"],'
    '"reviews":[{"id":"composition","label":"构图镜头专家","passed":true,'
    '"detail_score":0.0,"factual_score":0.0,"boundary_score":0.0,'
    '"missing":["缺少的维度"],"unsupported":["不属实或越界内容"],'
    '"retry_instruction":"打回重写时必须补足/修正的要求"}]}。'
    "专家初稿 JSON: {expert_observations}"
)

EXPERT_IMAGE_MERGE_TEMPLATE = (
    "你是图片反推专家组最终合并器。下面是多个专家从不同维度得到的 JSON 观察。"
    "请结合原图和专家观察，去重、消解冲突、保留不确定性，输出最终可用于复刻画面的标准 JSON。"
    "必须只输出一个有效 JSON 对象，不要 markdown，不要解释。"
    "顶层键固定为 visual_evidence, keyword_prompt, english_prompt, structured_prompt, structured_prompt_en。"
    "visual_evidence 是内部证据表，必须完整输出但不要混入 structured_prompt。"
    f"{VISUAL_EVIDENCE_GUIDE}"
    "structured_prompt 必须使用中文领域分组结构，形如："
    '{"画面描述":{"场景":{},"人物":{},"构图镜头":{},"摄影参数":{},"颜色光影":{},"氛围风格":{},'
    '"肢体动作":{},"表情语言":{},"服装妆容":{},"材质纹理":{},"性内容边界":{},'
    '"细节与文字":{},"复刻约束":{}},"负面提示词":{"构图镜头":[],"人物肢体":[],'
    '"服装材质":[],"性内容边界":[],"背景道具":[],"质量错误":[],"其他":[]}}。'
    "structured_prompt_en 使用相同含义的英文分组键，至少包含 image_description 和 negative_prompt。"
    "每个领域分组内部用对象或数组写高密度可见事实，不要把所有内容塞进一个长字符串；"
    "合并规则：structured_prompt 是事实源，keyword_prompt 从画面描述归纳；遮挡/裁切写入构图镜头或肢体动作；"
    "必须遵循高成功率提示词规格书："
    f"{_prompt_optimizer.HIGH_SUCCESS_PROMPT_SPEC_GUIDE}"
    "同时遵循反推闭环技能："
    f"{REVERSE_PROMPT_SKILL_GUIDE}"
    "最终画面描述只能复述 visual_evidence 中 allow_positive=true 且 confidence>=0.75 的事实；"
    "专家合并时，复刻约束用于锁定身份、构图、姿态、颜色、材质、文字版式和图像模型关键控制点；"
    "最终 structured_prompt.画面描述 只能保留确定可见事实，禁止保留“可能、疑似、不确定、无法确认、A或B”等不绝对提示词；这些内容只能进入 expert_observations.uncertain 或被省略；"
    "合并时不能因为原始描述方向不完整就删除动作；必须回看原图和专家观察，把动作补成带参照物的描述，并按画面外围到中心、左上/右上/左下/右下、左侧到右侧的空间顺序保留区域细节；"
    "人物分组必须包含可见外貌倾向和肤色；如无法可靠判断外貌倾向则省略，不得虚构真实族裔身份；"
    "肢体动作必须保留腿部可见起止边界、不完整展示区域、身体朝向、左右肢体方向和真实接触关系；"
    "肢体动作分组必须优先保留整体姿态、支撑点、身体朝向、手臂端点、腿部边界、接触遮挡这些键；"
    "坐姿必须细分为正坐、侧坐、半跪坐、跪坐、蹲坐、盘腿坐、跨坐、倚坐或斜坐，并写清臀部/大腿/膝盖/脚掌支撑关系；"
    "蹲姿和半蹲必须区分：双脚/鞋底落地承重、膝盖屈曲靠近身体时，应写蹲姿/下蹲/蹲坐；不能因为膝盖弯曲就写膝盖支撑在地面或岩石上；"
    f"{CAR_FRONT_SEAT_POSE_STANDARD}"
    f"{BEDROOM_SEATED_POSE_STANDARD}"
    "禁止把“坐姿”合并成普通坐姿；禁止用“双腿并拢或轻微分开”等二选一模糊句；遮挡导致无法判定时写具体遮挡原因或放入 uncertain；"
    "车内座椅姿态合并时，若膝盖/小腿支撑在座椅坐垫上，应写“人物跪坐在车厢前排座椅上，面部朝向镜头，躯干转向座椅靠背方向”这类完整姿态句；"
    "如果专家观察出现“面部朝向镜头、躯干转向座椅靠背、手臂伸向座椅靠背并到达画面边缘”，合并时必须保留这些参照物，不得简化为“坐姿挺拔/手臂向前伸展”；"
    "画幅比例必须根据原图宽高判断：竖版手机图写 9:16/2:3/竖幅，横图写横幅，正方形图才写 1:1；不得把竖图误写成 1:1 正方形；"
    "裁切边界必须保留实际可见范围，只看到头部到大腿/膝上/膝盖时，不能写全身、脚踝或脚部可见；如果鞋子和双脚位置进入画面，必须写头部到鞋子/近全身/全身入镜，不能写上半身至大腿区域；"
    "视角必须依据镜头高度、地平线和透视判断；人物蹲低不等于低角度仰视，若镜头略高于蹲姿人物或接近平视，应写轻微俯视/近似平视，不得写略微仰视；"
    "方向和相对位置必须用画面坐标表达：画面左/右/上/下、前景/中景/背景、人物左/右侧、镜头近端/远端；"
    "方向词必须附带参照系；不要剔除无参照的“手臂向前伸展/身体朝前”，要合并成“面部朝镜头，躯干朝座椅靠背，手臂向座椅靠背方向延伸到画面边缘”这类结构；"
    "物体关系必须核验是否真实接触或遮挡，不得按场景常识补写动作，例如车内方向盘不能自动合并为手搭方向盘；"
    "车内位置和窗外景观不能过度确定：座位关系不明确写车厢前排区域，绿色窗外只写草地/植被/路边绿地，不能自动合并为田野/农田；"
    "表情合并必须依据五官事实；嘴唇闭合且嘴角不明显时写平静闭唇，不能写嘴角微扬或浅笑；"
    "衣物文字必须只写可靠可读内容；若字母被遮挡、镜像、褶皱或分辨率影响，写“大号白色英文字母印花/局部红黄条纹贴片”，不得强行写 DMEE 等具体字母；"
    "肢体、表情五官、脸部妆造、服装、构图、摄影参数、材质必须按领域保留细节；NSFW/裸露/性内容只写可见事实，年龄不确定时不得补写性化细节；"
    "普通短裤、露出大腿皮肤、黑色过膝丝袜、日常休闲服装不等于 NSFW/adult_nudity；只有可见成人裸露、性器官、性意味接触或性液体时才写 NSFW/adult_nudity/explicit_sexual_content 标签；"
    "低领吊带、乳沟、贴身胸部轮廓、短裤和长筒袜可写 suggestive_clothing/cleavage_visible，但不能写 adult_nudity，除非乳头或裸露乳房清晰可见；"
    "服装妆容必须特别保留袜子/过膝袜/长筒袜/大腿袜/丝袜/连裤袜/内衣/泳装/肩带/腰头/罩杯/蕾丝/缝线/透明度/光泽/贴合度等局部服饰细节，不能按常识补全或替换款式；"
    "袜类合并必须区分长度款式与材质本质：过膝袜/长筒袜/大腿袜不等同于丝袜/连裤袜；要分别保留袜口位置、覆盖范围、尼龙半透明、细网纹、光泽和贴肤度；"
    "如果长度和材质都可见，最终应合成为“黑色过膝丝袜/黑色大腿丝袜”等复合词，而不是只写黑色过膝袜或黑色丝袜；"
    "颜色光影必须写具体颜色名和近似 HEX 色值，并绑定到对象；不要只写粉色/粉色系/蓝色系/暖色系/冷色系；"
    "光线必须写色温或冷暖参考；材质纹理必须写反光、透光、粗糙度、织法、纹理密度、颗粒度和锐度等可复刻细节；"
    "摄影参数可以写明确的生图参考参数，不代表真实 EXIF；可写参考光圈、快门、ISO、曝光、采光度、白平衡、焦段和手机/相机感；"
    "光圈术语必须准确：f/2.8-f/4 是大光圈或中大光圈，不是小光圈；f/8-f/16 才可称小光圈；"
    "最终提示词不要出现“推断、估计、可能是参数”等分析词，应写“参考参数：35mm，f/2.8，1/125s，ISO 400，浅景深”等可给生图模型参考的参数；"
    "structured_prompt.负面提示词 必须是 structured_prompt 下与 画面描述 同级的对象，绝不能嵌入 structured_prompt.画面描述 内部；"
    "structured_prompt.负面提示词只能写要规避的纯短语/标签，不得包含“不要/避免/禁止/no/avoid/do not”等命令词；"
    "所有负面语义不得混入 structured_prompt.画面描述；删除重复字段和泛化空值，"
    "不要把不可见脚写成脚部细节不清晰，不要把低角度仰拍写成平视，不要把疑似衣物强行确定。"
    "专家观察 JSON: {expert_observations}\n"
)

FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE = (
    "你是图片反推专家组的快速总控。请在一次视觉观察中分别完成多个专家维度，避免重复和长篇解释。"
    "专家反推定位：1:1 复刻精度的图像规格书，不是普通准确描述；必须尽可能把可见内容拆成可执行的复刻参数。"
    "专家结果必须比标准反推更细：构图比例、主体占比、裁切边界、姿态关节、五官妆造、服装局部、袜子/丝袜/内衣、"
    "颜色 HEX、色温、摄影参考参数、材质颗粒度、纹理密度、反光透光、背景物件、人物肤色、可见外貌倾向和遮挡关系都要分领域写清。"
    "必须只输出一个有效 JSON 对象，不要 markdown，不要解释。"
    "顶层键固定为 visual_evidence, keyword_prompt, english_prompt, structured_prompt, structured_prompt_en, expert_observations。"
    "visual_evidence 是内部证据表，必须完整输出但不要混入 structured_prompt。"
    f"{VISUAL_EVIDENCE_GUIDE}"
    "structured_prompt 必须为中文分组："
    '{"画面描述":{"场景":{},"人物":{},"构图镜头":{},"摄影参数":{},"颜色光影":{},"氛围风格":{},'
    '"肢体动作":{},"表情语言":{},"服装妆容":{},"材质纹理":{},"性内容边界":{},'
    '"细节与文字":{},"复刻约束":{}},"负面提示词":{"构图镜头":[],"人物肢体":[],'
    '"服装材质":[],"性内容边界":[],"背景道具":[],"质量错误":[],"其他":[]}}。'
    "JSON 必须结构化排列：画面描述各领域只写正向可见事实；复刻约束写应保持的正向约束；"
    "负面提示词单独收集所有要规避的纯短语/标签；不要把负面约束混入画面描述。"
    "画面描述禁止使用不绝对的二选一和猜测词，例如“并拢或轻微分开、短裙或短裤、可能、疑似、不确定、无法确认”；判断不了就省略该状态，只写可见裁切、遮挡和支撑关系。"
    "负面提示词字段禁止写自然语言命令，不能出现“不要、避免、禁止、no、avoid、do not”；"
    "例如要规避露出脸部就写“脸部”，要规避双腿交叉就写“双腿交叉”，要规避水印就写“水印/watermark”。"
    "按图像模型用词组织：Qwen Image 可使用正向短句加负面标签；FLUX.2 和 Z-Image Turbo 更依赖正向描述，负面只作为通用规避集合。"
    "必须遵循高成功率提示词规格书："
    f"{_prompt_optimizer.HIGH_SUCCESS_PROMPT_SPEC_GUIDE}"
    "同时遵循反推闭环技能："
    f"{REVERSE_PROMPT_SKILL_GUIDE}"
    "最终画面描述只能复述 visual_evidence 中 allow_positive=true 且 confidence>=0.75 的事实；"
    "复刻约束用于锁定身份、构图、姿态、颜色、材质、文字版式和图像模型关键控制点；"
    "expert_observations 必须是 9 项完整数组，每项包含 id,label,summary,observations,negative_constraints,confidence；"
    "id 必须覆盖 composition,photography_parameters,color_light,mood_style,body_pose,expression_language,sexual_boundary,clothing_makeup,materials_texture。"
    "每个专家 summary 不超过 45 个汉字，observations 最多 3 条，negative_constraints 最多 2 条。"
    "专家观察必须按区域扫描补足信息：画面外围到中心、左上角到右下角、左侧到右侧、前景到背景；每个区域写可见物体、人物/肢体朝向、接触、遮挡和裁切线。"
    "必须写清构图裁切、主体占比、摄影参数视觉效果、人物外貌倾向、肤色、动作姿态、手脚关节、腿部可见起止边界、脸部表情、五官细节、脸部妆造、服装版型、袜子/丝袜/内衣等局部服饰、材质纹理、光影颜色。"
    "肢体动作字段必须拆成整体姿态、支撑点、身体朝向、手臂端点、腿部边界、接触遮挡；不要把这些压缩成“坐姿”。"
    f"{CAR_FRONT_SEAT_POSE_STANDARD}"
    f"{BEDROOM_SEATED_POSE_STANDARD}"
    "坐姿不得只写“坐在xxx”，必须写成正坐/侧坐/半跪坐/跪坐/蹲坐/盘腿坐/跨坐/倚坐/斜坐等具体类型和可见支撑点。"
    "蹲姿和半蹲必须区分：双脚/鞋底落地承重、膝盖屈曲靠近身体时，应写蹲姿/下蹲/蹲坐；不能因为膝盖弯曲就写膝盖支撑在地面或岩石上。"
    "海边石滩这类地面蹲姿，若鞋底踩在石头上，应写“人物下蹲/蹲姿，鞋底踩在碎石地面承重”；"
    "禁止写“半蹲坐姿 (Half-crouching Sit)”“双膝和小腿接触于前景岩石表面”“膝盖支撑在岩石上”，除非膝盖或小腿真实压在地面并清晰可见。"
    "鞋子覆盖脚踝或鞋口遮挡脚踝时，不得写“小腿和脚踝区域被黑色丝袜包裹”；只能写可见小腿/膝上腿部被黑色过膝丝袜覆盖，鞋口处形成遮挡。"
    "手部端点必须按画面坐标和可见接触点写，例如“画面右侧手臂弯曲抬起，手靠近画面右侧太阳穴/发丝”；"
    "不要强行写人物左手/右手或“头部左上方发梢”，除非左右身份和接触点清晰可见。"
    "车内座椅上膝盖/小腿支撑时，整体姿态必须写“人物跪坐在车厢前排座椅上，面部朝向镜头，躯干转向座椅靠背方向”这类结构化句子。"
    "类似该标准图时，身体朝向写“面部朝向镜头，躯干转向座椅靠背方向”，手臂端点写“手臂向座椅靠背方向延伸到画面边缘”。"
    "画幅比例必须根据原图宽高判断：竖版手机图写 9:16/2:3/竖幅，横图写横幅，正方形图才写 1:1；不得把竖图误写成 1:1 正方形。"
    "裁切边界必须精确；只看到头部到大腿/膝上/膝盖时，不能写包含脚踝、脚部或全身；如果鞋子和双脚位置进入画面，必须写头部到鞋子/近全身/全身入镜，不能写上半身至大腿区域。"
    "视角必须依据镜头高度、地平线和透视判断；人物蹲低不等于低角度仰视，若镜头略高于蹲姿人物或接近平视，应写轻微俯视/近似平视，不得写略微仰视。"
    "禁止输出“双腿并拢或轻微分开”等二选一模糊句，必须选择可见事实或写入不确定原因。"
    "场景不是恒定语义，所有人物/肢体方向和物品相对位置必须按画面坐标描述：画面左/右/上/下、前景/中景/背景、人物左/右侧、镜头近端/远端。"
    "前/后/左/右/向前必须写明参照物；不要剔除动作，应把无参照的“手臂向前伸展”补写成向画面左侧、向镜头、向座椅靠背、向人物身体前方等可见方向。"
    "必须确认手、脚、身体和物体之间是否真实接触、遮挡或仅相邻；不得因为场景物件存在就补写动作，例如车内有方向盘不等于手搭方向盘。"
    "车内位置只能按可见座位和方向盘关系判断；不明确时写车厢前排区域，不要强行写驾驶座/副驾驶座。"
    "窗外绿色只写草地/植被/路边绿地等可见事实，不要自动写远处田野/农田。"
    "嘴角微扬、浅笑、露齿等表情必须有可见嘴角或牙齿依据；闭唇表情默认写平静闭唇。"
    "衣物文字必须只写可靠可读内容；若字母被遮挡、镜像、褶皱或分辨率影响，写“大号白色英文字母印花/局部红黄条纹贴片”，不得强行写 DMEE 等具体字母。"
    "颜色光影必须写具体颜色名和近似 HEX 色值，并绑定到对象；不要只写粉色/粉色系/蓝色系/暖色系/冷色系。"
    "光线必须写色温或冷暖参考，例如暖白光 3200K-4000K、自然日光 5000K-5600K、冷白光 6500K；"
    "材质纹理必须写反光、透光、粗糙度、织法、纹理密度、颗粒度和锐度等可复刻细节。"
    "服装妆容必须特别检查袜子、短袜、长袜、过膝袜、长筒袜、大腿袜、连裤袜、丝袜、吊带袜、内衣、胸罩、文胸、内裤、泳装、打底裤；"
    "袜类必须区分长度款式与材质本质：过膝袜/长筒袜/大腿袜描述袜口和覆盖范围，丝袜/连裤袜描述尼龙半透明、细网纹、光泽和贴肤度；"
    "当长度和材质都可见时必须使用复合词，例如黑色过膝丝袜、黑色大腿丝袜；"
    "黑色过膝袜不能直接替代黑色丝袜，半透明丝袜不能写成普通黑色棉袜或裸腿。"
    "若可见，写清款式、长度、腰头/袜口/肩带/罩杯/钢圈/蕾丝/缝线/花边/蝴蝶结/透明度/光泽/贴合度/褶皱/遮挡边界；"
    "看不清就省略具体款式或写入 expert_observations.uncertain，不要把丝袜误写成裸腿，不要把内衣误写成普通上衣，不要把短裤/短裙/内裤强行互相替换。"
    "摄影参数可以写明确的生图参考参数，不代表真实 EXIF；可写参考光圈、快门、ISO、曝光、采光度、白平衡、焦段和手机/相机感。"
    "光圈术语必须准确：f/2.8-f/4 是大光圈或中大光圈，不是小光圈；f/8-f/16 才可称小光圈。"
    "最终提示词不要出现“推断、估计、可能是参数”等分析词，应写“参考参数：35mm，f/2.8，1/125s，ISO 400，浅景深”等可给生图模型参考的参数。"
    "如果存在成人裸露、性器官、性意味接触或液体，性内容边界必须写可见事实和 NSFW/adult_nudity 标签；"
    "普通短裤、露出大腿皮肤、黑色过膝丝袜、日常休闲服装不等于 NSFW/adult_nudity；只有可见成人裸露、性器官、性意味接触或性液体时才写 NSFW/adult_nudity/explicit_sexual_content 标签；"
    "低领吊带、乳沟、贴身胸部轮廓、短裤和长筒袜可写 suggestive_clothing/cleavage_visible，但不能写 adult_nudity，除非乳头或裸露乳房清晰可见；"
    "如果年龄不明确，只描述非性化可见事实和年龄不确定，不写性化细节。"
    "没看到的身体部位不要提及名称；只描述可见的画幅边界、可见衣物、可见肢体和可见遮挡物。"
    "例如不要写“双脚不可见/隐私部位不可见”，应写“画面边缘裁切在腿部区域”或“衣物与大腿形成遮挡边界”。"
    "负面提示词不要写命令句；如需防止模型补全不可见内容，写“多余肢体补全、额外身体细节”等纯短语。"
    "负面提示词必须是 structured_prompt 下与 画面描述 同级的对象，绝不能嵌入 structured_prompt.画面描述 内部。"
    "正向提示词和画面描述只能写看见了什么，禁止写“无明显、没有明显、未见、无可见、局部暴露、部分暴露、尺度较大、性感、诱人”等含糊判断；"
    "缺失/否定/不可确认内容放入 expert_observations.uncertain、negative_constraints 或负面提示词；可见裸露必须写具体部位和衣物遮挡边界。"
    "keyword_prompt 不超过 220 个汉字，english_prompt 不超过 110 个英文词；整体不超过 820 tokens。"
)


RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE = (
    "你是图片反推专家组快速总控，目标是 1:1 复刻精度。必须只输出有效 JSON，不要 markdown。"
    "输出必须以 { 开头、以 } 结尾；所有键必须用英文双引号；禁止中文逗号、未加引号的键、JSON 外文本。"
    "所有内容统一使用中文，不要中英混写。每个专家只能输出自己边界内的观点，不能替其他专家做结论。"
    "顶层键固定为 visual_evidence, expert_observations, keyword_prompt, negative_prompt。"
    "不要输出 structured_prompt；系统会根据专家字段重新封装最终 JSON。"
    "visual_evidence 是内部证据简表，值可以是字符串或数组，必须覆盖以下键："
    "aspect_ratio, visible_body_range, support_points, hand_endpoints, foot_or_shoe_contact, "
    "clothing_materials, visible_text_confidence, nsfw_visible_evidence, foreground_background_regions。"
    "expert_observations 必须是对象，9 个键固定为 composition,photography_parameters,color_light,mood_style,body_pose,expression_language,sexual_boundary,clothing_makeup,materials_texture；"
    "9 个专家键必须全部出现；某个维度只能写很少内容时也保留该键并写可见事实，不能只输出 3-4 个专家。"
    "每个专家值用对象表达，如 {\"姿势\":\"...\",\"手部\":\"...\"}，每个专家最多 100 字，最多 4 个字段。"
    "keyword_prompt 是 180 个汉字内的正向复刻短段；negative_prompt 是纯短语数组。"
    "只写可见事实；看不见、不确定、常识补全、二选一和猜测词不得进入 keyword_prompt 或专家字段。"
    "按画面坐标扫描：上到下、左到右、前景到背景；方向必须带参照物，如画面左侧、镜头近端、座椅靠背方向。"
    "人物必须写可见外貌倾向、肤色、发型、五官表情、身体可见范围、裁切线和遮挡边界；不可靠就省略。"
    "肢体动作必须拆成整体姿态、支撑点、身体朝向、手臂端点、腿部边界、接触遮挡；坐/蹲/跪必须分类。"
    "蹲姿中鞋底踩地承重不能写膝盖支撑地面；车内有方向盘不能自动写手搭方向盘；绿色窗外只写草地/植被，不能自动写农田。"
    f"{CAR_FRONT_SEAT_POSE_STANDARD}"
    f"{BEDROOM_SEATED_POSE_STANDARD}"
    "构图必须写真实画幅比例、主体占比、视角、裁切到哪里；竖图不能写 1:1，鞋子入镜不能写只到大腿。"
    "服装写版型、领口/肩带/袖口/腰头/裙摆/裤脚/褶皱/蕾丝/缝线/贴合度；袜类同时可见长度和尼龙质感时写黑色过膝丝袜或黑色大腿丝袜。"
    "颜色绑定对象并给具体色名和近似 HEX；摄影参数写生图参考值，不写推断/估计，f/2.8-f/4 是大光圈或中大光圈。"
    "性内容边界只写可见事实；普通短裤、大腿皮肤、乳沟、贴身胸部轮廓不等于 adult_nudity。"
    "只有清晰可见成人裸露、乳头/性器官、性意味接触或液体时才写 NSFW/adult_nudity/explicit_sexual_content。"
    "负面提示词只能是纯短语/标签，不能出现不要、避免、禁止、no、avoid、do not。"
    "示例结构："
    '{"visual_evidence":{"aspect_ratio":"9:16","visible_body_range":"头部到膝部","support_points":["坐在床面"],"hand_endpoints":["画面左侧手靠近镜头"],"foot_or_shoe_contact":"画面裁切到膝部","clothing_materials":["白色蕾丝吊带"],"visible_text_confidence":0,"nsfw_visible_evidence":"低领和乳沟可见","foreground_background_regions":["前景手部","背景床铺"]},'
    '"expert_observations":{"composition":{"构图":"..."},"photography_parameters":{"参考参数":"..."},"color_light":{"颜色光影":"..."},'
    '"mood_style":{"氛围":"..."},"body_pose":{"姿势":"..."},"expression_language":{"表情五官":"..."},'
    '"sexual_boundary":{"可见事实":"..."},"clothing_makeup":{"服装":"..."},"materials_texture":{"材质":"..."}},'
    '"keyword_prompt":"...","negative_prompt":["水印"]}。'
)

LEGACY_RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE = (
    "保留的旧版专家反推长协议，供测试和文档引用。"
    "顶层键固定为 visual_evidence, keyword_prompt, english_prompt, structured_prompt, structured_prompt_en, expert_observations。"
    "visual_evidence 是内部证据表；每项必须含 value,evidence,confidence,allow_positive。"
    "必填证据键：aspect_ratio, visible_body_range, support_points, hand_endpoints, foot_or_shoe_contact, "
    "clothing_materials, visible_text_confidence, nsfw_visible_evidence, foreground_background_regions。"
    "structured_prompt 格式："
    '{"画面描述":{"场景":{},"人物":{},"构图镜头":{},"摄影参数":{},"颜色光影":{},"氛围风格":{},'
    '"肢体动作":{},"表情语言":{},"服装妆容":{},"材质纹理":{},"性内容边界":{},'
    '"细节与文字":{},"复刻约束":{}},"负面提示词":{"构图镜头":[],"人物肢体":[],'
    '"服装材质":[],"性内容边界":[],"背景道具":[],"质量错误":[],"其他":[]}}。'
    "最终画面描述只能复述 allow_positive=true 且 confidence>=0.75 的可见事实；"
    "看不见、不确定、常识补全、二选一和猜测词不得进入正向提示词。"
    "按画面坐标扫描：上到下、左到右、前景到背景；方向必须带参照物，如画面左侧、镜头近端、座椅靠背方向。"
    "人物必须写可见外貌倾向、肤色、发型、五官表情、身体可见范围、裁切线和遮挡边界；不可靠就省略。"
    "肢体动作必须拆成整体姿态、支撑点、身体朝向、手臂端点、腿部边界、接触遮挡；"
    "坐/蹲/跪必须分类，写清臀部/大腿/膝盖/鞋底/脚掌的真实承重点。"
    "蹲姿中鞋底踩地承重不能写膝盖支撑地面；车内有方向盘不能自动写手搭方向盘；绿色窗外只写草地/植被，不能自动写农田。"
    f"{CAR_FRONT_SEAT_POSE_STANDARD}"
    f"{BEDROOM_SEATED_POSE_STANDARD}"
    "构图必须写真实画幅比例、主体占比、镜头距离、视角、裁切到哪里；竖图不能写 1:1，鞋子入镜不能写只到大腿。"
    "服装必须写版型、领口/肩带/袖口/腰头/裙摆/裤脚/褶皱/蕾丝/缝线/贴合度。"
    "袜类必须区分长度和材质；长度加尼龙半透明/细网纹/光泽同时可见时写黑色过膝丝袜或黑色大腿丝袜。"
    "颜色要绑定对象并给具体色名和近似 HEX；摄影参数写生图参考值，不写“推断/估计”，f/2.8-f/4 是大光圈或中大光圈。"
    "性内容边界只写可见事实；普通短裤、大腿皮肤、乳沟、贴身胸部轮廓不等于 adult_nudity。"
    "只有清晰可见成人裸露、乳头/性器官、性意味接触或液体时才写 NSFW/adult_nudity/explicit_sexual_content；年龄不明确时只写非性化可见事实。"
    "负面提示词只能是纯短语/标签，不能出现不要、避免、禁止、no、avoid、do not；负面不得嵌入画面描述。"
    "expert_observations 必须是 9 项数组，id 覆盖 composition,photography_parameters,color_light,mood_style,body_pose,expression_language,sexual_boundary,clothing_makeup,materials_texture；"
    "每项含 id,label,summary,observations,negative_constraints,confidence，summary 不超过 45 个汉字，observations 最多 3 条。"
    "keyword_prompt 不超过 220 个汉字，english_prompt 不超过 110 个英文词。"
)


def build_image_interrogate_workflow(image_filename: str) -> dict[str, dict[str, Any]]:
    """Build a fast single-VLM image interrogation workflow with WD14 metadata fallback."""
    image_name = str(image_filename or "").replace("\\", "/").lstrip("/")
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        },
        "2": {
            "class_type": "WD14Tagger|pysssss",
            "inputs": {
                "image": ["1", 0],
                "model": "wd-v1-4-moat-tagger-v2",
                "threshold": 0.35,
                "character_threshold": 0.85,
                "replace_underscore": True,
                "trailing_comma": False,
                "exclude_tags": "",
            },
        },
        "3": {
            "class_type": "ShowText|pysssss",
            "inputs": {"text": ["2", 0]},
        },
        "4": {
            "class_type": "ImageScaleToMaxDimension",
            "inputs": {
                "image": ["1", 0],
                "upscale_method": "lanczos",
                "largest_size": 1024,
            },
        },
        "5": {
            "class_type": "Qwen3_VQA",
            "inputs": {
                "image": ["4", 0],
                "text": QWEN_IMAGE_INTERROGATE_TEMPLATE,
                "model": "Qwen3-VL-4B-Instruct",
                "quantization": "4bit",
                "keep_model_loaded": True,
                "temperature": 0.15,
                "max_new_tokens": 3072,
                "min_pixels": 3136,
                "max_pixels": 802816,
                "seed": 1,
                "attention": "sdpa",
            },
        },
        "6": {
            "class_type": "ShowText|pysssss",
            "inputs": {"text": ["5", 0]},
        },
    }


def _safe_input_path(input_dir: str, image_filename: str) -> tuple[str, str]:
    safe = str(image_filename or "").replace("\\", "/").lstrip("/")
    input_root = os.path.abspath(input_dir)
    path = os.path.abspath(os.path.join(input_root, safe))
    if os.path.commonpath([input_root, path]) != input_root:
        raise RuntimeError(f"非法反推图片路径: {image_filename}")
    return safe, path


def prepare_interrogate_image(
    image_filename: str,
    input_dir: str,
    max_side: int = INTERROGATE_MAX_IMAGE_SIDE,
    max_pixels: int = INTERROGATE_MAX_IMAGE_PIXELS,
) -> dict[str, Any]:
    """Create a smaller image for interrogation when the uploaded image is large."""
    safe, src = _safe_input_path(input_dir, image_filename)
    if not os.path.isfile(src):
        raise RuntimeError(f"反推图片不存在: {image_filename}")

    try:
        from PIL import Image, ImageOps
    except Exception as e:
        return {
            "filename": safe,
            "optimized": False,
            "reason": f"pillow_unavailable: {e}",
        }

    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img)
        width, height = img.size
        pixel_count = width * height
        side_limit = max(256, int(max_side or INTERROGATE_MAX_IMAGE_SIDE))
        pixel_limit = max(256 * 256, int(max_pixels or INTERROGATE_MAX_IMAGE_PIXELS))
        needs_resize = width > side_limit or height > side_limit or pixel_count > pixel_limit
        if not needs_resize:
            return {
                "filename": safe,
                "optimized": False,
                "width": width,
                "height": height,
                "pixels": pixel_count,
            }

        img.thumbnail((side_limit, side_limit), Image.Resampling.LANCZOS)
        if img.width * img.height > pixel_limit:
            scale = (pixel_limit / float(img.width * img.height)) ** 0.5
            resized = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            img = img.resize(resized, Image.Resampling.LANCZOS)
        if img.mode not in ("RGB", "L"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if "A" in img.getbands():
                background.paste(img, mask=img.getchannel("A"))
            else:
                background.paste(img)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        base_dir = os.path.dirname(safe)
        stem = os.path.splitext(os.path.basename(safe))[0]
        optimized_rel = "/".join(part for part in (base_dir, "_interrogate", f"{stem}_max{side_limit}.jpg") if part)
        _, dest = _safe_input_path(input_dir, optimized_rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        img.save(dest, "JPEG", quality=88, optimize=True)
        final_width, final_height = img.size

    return {
        "filename": optimized_rel,
        "optimized": True,
        "original_filename": safe,
        "original_width": width,
        "original_height": height,
        "original_pixels": pixel_count,
        "width": final_width,
        "height": final_height,
        "pixels": final_width * final_height,
        "max_side": side_limit,
    }


def _text_output(outputs: dict[str, Any], node_id: str) -> str:
    node_out = outputs.get(str(node_id), {})
    text = node_out.get("text") if isinstance(node_out, dict) else None
    if isinstance(text, list) and text:
        if isinstance(text[0], list) and text[0]:
            return str(text[0][0]).strip()
        return str(text[0]).strip()
    if isinstance(text, str):
        return text.strip()
    return ""


def _tag_output(outputs: dict[str, Any], node_id: str) -> str:
    node_out = outputs.get(str(node_id), {})
    tags = node_out.get("tags") if isinstance(node_out, dict) else None
    if isinstance(tags, list) and tags:
        return str(tags[0]).strip()
    if isinstance(tags, str):
        return tags.strip()
    return ""


def _is_tag_like_prompt_line(text: str) -> bool:
    """Detect WD14/booru-style comma tag lines that should not become final prompts."""
    line = str(text or "").strip().strip(".。")
    if not line:
        return False
    parts = [part.strip() for part in re.split(r"[,，]", line) if part.strip()]
    if len(parts) < 4:
        return False
    if re.search(r"[.。!?！？]", line):
        return False
    short_parts = 0
    for part in parts:
        words = [word for word in re.split(r"\s+", part) if word]
        if len(words) <= 3 and len(part) <= 36:
            short_parts += 1
    return short_parts / max(1, len(parts)) >= 0.75


def _paragraph_similarity(a: str, b: str) -> float:
    a_norm = re.sub(r"\s+", " ", str(a or "").strip().lower())
    b_norm = re.sub(r"\s+", " ", str(b or "").strip().lower())
    if not a_norm or not b_norm:
        return 0.0
    return max(
        difflib.SequenceMatcher(None, a_norm, b_norm).ratio(),
        difflib.SequenceMatcher(None, b_norm, a_norm).ratio(),
    )


def _paragraph_token_overlap(a: str, b: str) -> float:
    words_a = {
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z'-]{2,}", str(a or "").lower())
        if word not in {"the", "and", "with", "this", "that", "image", "itself", "even", "more"}
    }
    words_b = {
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z'-]{2,}", str(b or "").lower())
        if word not in {"the", "and", "with", "this", "that", "image", "itself", "even", "more"}
    }
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(1, min(len(words_a), len(words_b)))


def _clean_promptgen_text(text: str) -> str:
    """Keep Florence's natural caption and remove duplicate/tagger fragments."""
    normalized = str(text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", normalized) if block.strip()]
    if not blocks:
        blocks = [normalized]
    cleaned_blocks: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        prose_lines = [line for line in lines if not _is_tag_like_prompt_line(line)]
        prose = " ".join(prose_lines).strip()
        if not prose:
            continue
        if any(
            _paragraph_similarity(prose, previous) >= 0.58
            or _paragraph_token_overlap(prose, previous) >= 0.55
            for previous in cleaned_blocks
        ):
            continue
        cleaned_blocks.append(prose)
    return "\n\n".join(cleaned_blocks).strip()


def _repair_model_json_artifacts(text: str) -> str:
    """Repair common near-JSON artifacts from small VLMs before strict parsing."""
    raw = str(text or "").strip()
    previous = None
    while raw != previous:
        previous = raw
        raw = re.sub(r',\s*"\s*([\]}])\s*"\s*,', r"\1,", raw)
        raw = re.sub(r',\s*"\s*([\]}])\s*,\s*(?=")', r"\1,", raw)
        raw = re.sub(r',\s*"\s*([\]}])\s*"\s*(?=")', r"\1,", raw)
    return raw


def _first_complete_json_object_text(text: str) -> str:
    raw = str(text or "")
    start = raw.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(raw)):
        char = raw[idx]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return raw[start : idx + 1]
    return ""


def _extract_json_object(text: str) -> dict[str, Any] | None:
    normalized = str(text or "").strip()
    normalized = re.sub(r"^```(?:json)?\s*", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s*```$", "", normalized)
    candidates = [normalized]
    start = normalized.find("{")
    end = normalized.rfind("}")
    if start >= 0 and end > start:
        candidates.append(normalized[start : end + 1])
    first_complete = _first_complete_json_object_text(normalized)
    if first_complete:
        candidates.append(first_complete)
    expanded_candidates: list[str] = []
    for candidate in candidates:
        if candidate not in expanded_candidates:
            expanded_candidates.append(candidate)
        artifact_repaired = _repair_model_json_artifacts(candidate)
        if artifact_repaired and artifact_repaired not in expanded_candidates:
            expanded_candidates.append(artifact_repaired)
        repaired = _repair_truncated_json(candidate)
        if repaired and repaired not in expanded_candidates:
            expanded_candidates.append(repaired)
        repaired_artifacts = _repair_truncated_json(artifact_repaired)
        if repaired_artifacts and repaired_artifacts not in expanded_candidates:
            expanded_candidates.append(repaired_artifacts)
    for candidate in expanded_candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except Exception:
            try:
                parsed = ast.literal_eval(candidate)
            except Exception:
                continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and parsed:
            for item in parsed:
                if isinstance(item, dict):
                    return item
                nested = _extract_json_object(str(item))
                if nested:
                    return nested
    return None


def _extract_json_string_field(text: str, field: str) -> str:
    """Extract a simple JSON string field from near-JSON when full parsing fails."""
    pattern = r'"' + re.escape(field) + r'"\s*:\s*"((?:\\.|[^"\\])*)'
    match = re.search(pattern, str(text or ""), flags=re.DOTALL)
    if not match:
        return ""
    value = match.group(1)
    try:
        return json.loads(f'"{value}"').strip()
    except Exception:
        return value.replace(r"\"", '"').replace(r"\n", "\n").strip()


NEAR_JSON_STRUCTURED_STRING_FIELDS = (
    "subject",
    "subject_attributes",
    "action",
    "pose_details",
    "hand_details",
    "foot_details",
    "joint_body_mechanics",
    "facial_expression_details",
    "occlusion_crop_details",
    "exposed_body_details",
    "intimate_body_details",
    "sexual_act_details",
    "genital_details",
    "fluid_contact_details",
    "nsfw_content_details",
    "scene",
    "foreground",
    "midground",
    "background",
    "composition",
    "camera_lens",
    "lighting",
    "style",
    "color_palette",
    "mood_atmosphere",
)


def _near_json_object_section(text: str, field: str) -> str:
    raw = str(text or "")
    field_match = re.search(r'"' + re.escape(field) + r'"\s*:\s*\{', raw)
    if not field_match:
        return ""
    start = field_match.end()
    if field == "structured_prompt":
        next_match = re.search(r',\s*"?structured_prompt_en"?\s*:\s*\{', raw[start:])
        if next_match:
            return raw[start : start + next_match.start()]
    return raw[start:]


def _extract_near_json_structured_fields(text: str, field: str) -> dict[str, Any]:
    section = _near_json_object_section(text, field)
    if not section:
        return {}
    payload: dict[str, Any] = {}
    for key in NEAR_JSON_STRUCTURED_STRING_FIELDS:
        value = _extract_json_string_field(section, key)
        if value:
            payload[key] = value
    return payload


def _repair_truncated_json(text: str) -> str:
    """Best-effort close for local VLM JSON that is cut off at the final braces."""
    raw = str(text or "").strip()
    if not raw.startswith("{"):
        start = raw.find("{")
        if start < 0:
            return raw
        raw = raw[start:]
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in raw:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
    if in_string:
        raw += '"'
    if stack:
        raw += "".join(reversed(stack))
    return raw


GROUPED_DESCRIPTION_KEYS = ("画面描述", "image_description", "positive_prompt", "positive")
GROUPED_NEGATIVE_KEYS = ("负面提示词", "negative_prompt", "negative")
VAGUE_POSITIVE_RE = re.compile(
    r"无明显|没有明显|未见|未发现|无可见|不可见|看不见|看不清|不清晰|局部暴露|部分暴露|"
    r"尺度较大|暴露较多|较暴露|性感|诱人|色情感|性暗示较强",
    flags=re.IGNORECASE,
)
UNCERTAIN_POSITIVE_RE = re.compile(
    r"可能|疑似|似乎|大概|也许|不确定|无法确认|难以判断|看不准|不能确定|uncertain|possibly|maybe|probably",
    flags=re.IGNORECASE,
)
AMBIGUOUS_ALTERNATIVE_RE = re.compile(r"[\u3400-\u9fffA-Za-z0-9#./-]{1,24}或[\u3400-\u9fffA-Za-z0-9#./-]{1,24}")
ALLOWED_POSITIVE_ALTERNATIVES = ("大光圈或中大光圈",)
UNSEEN_BODY_PART_RE = re.compile(
    r"双脚|脚部|脚趾|足部|头顶|眼睛|眼部|隐私部位|私处|性器官|生殖器|外阴|阴道|阴唇|阴茎|睾丸|肛门|乳头|乳晕"
)


def _looks_like_grouped_prompt(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(key in value for key in GROUPED_DESCRIPTION_KEYS) or "负面提示词" in value


def _normalize_grouped_prompt_structure(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    grouped = copy.deepcopy(value)
    description = _grouped_section(grouped, GROUPED_DESCRIPTION_KEYS)
    if isinstance(description, dict):
        nested_negative = None
        for key in GROUPED_NEGATIVE_KEYS:
            if key in description:
                nested_negative = description.pop(key)
                break
        if nested_negative not in (None, "", [], {}):
            existing = _grouped_section(grouped, GROUPED_NEGATIVE_KEYS)
            grouped["负面提示词"] = {
                "结构迁移": _dedupe_prompt_items(
                    _iter_grouped_prompt_strings(existing) + _iter_grouped_prompt_strings(nested_negative)
                )
            }
    return grouped


def _prune_grouped_prompt_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            pruned = _prune_grouped_prompt_value(item)
            if pruned in ("", None, [], {}):
                continue
            cleaned[str(key)] = pruned
        return cleaned
    if isinstance(value, list):
        cleaned_items = []
        for item in value:
            pruned = _prune_grouped_prompt_value(item)
            if pruned in ("", None, [], {}):
                continue
            cleaned_items.append(pruned)
        return cleaned_items
    if isinstance(value, (tuple, set)):
        cleaned_items = []
        for item in value:
            pruned = _prune_grouped_prompt_value(item)
            if pruned in ("", None, [], {}):
                continue
            cleaned_items.append(pruned)
        return cleaned_items
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return ""
        generic = re.sub(r"[\s，,。.;；:：、/|()（）【】\[\]{}\"'“”‘’]+", "", cleaned).lower()
        if generic in {"无", "暂无", "没有", "不可见", "看不见", "不清晰", "none", "n/a", "notvisible"}:
            return ""
        return cleaned
    return value


def _clean_positive_prompt_text(text: str) -> str:
    parts = [part.strip() for part in re.split(r"[，,；;。\n]+", str(text or "")) if part.strip()]
    cleaned = []
    for part in parts:
        if _is_negative_prompt_fragment(part):
            continue
        if re.match(r"^(?:保持|保留|维持|keep\b|preserve\b|retain\b)", part, flags=re.IGNORECASE):
            continue
        if VAGUE_POSITIVE_RE.search(part):
            continue
        if UNCERTAIN_POSITIVE_RE.search(part):
            continue
        if AMBIGUOUS_ALTERNATIVE_RE.search(part) and not any(allowed in part for allowed in ALLOWED_POSITIVE_ALTERNATIVES):
            continue
        if UNSEEN_BODY_PART_RE.search(part) and re.search(r"画面外|裁切|遮挡|挡住|覆盖|遮住|不可见|未见|无可见", part):
            continue
        part = re.sub(r"(?:可见效果)?推断(?:为|出|：|:)?|据此推断|推测(?:为|出|：|:)?|估计(?:为|出|：|:)?|可能是参数|参数推断", "", part)
        part = re.sub(r"小光圈\s*[（(]\s*f/2\.8\s*[-–—~至到]\s*f/4(?:\.0)?\s*[）)]", "大光圈或中大光圈 f/2.8-f/4.0", part, flags=re.IGNORECASE)
        part = re.sub(r"小光圈\s*(f/2\.8\s*[-–—~至到]\s*f/4(?:\.0)?)", r"大光圈或中大光圈 \1", part, flags=re.IGNORECASE)
        part = re.sub(r"局部暴露|部分暴露|尺度较大|暴露较多|较暴露|性感|诱人", "", part, flags=re.IGNORECASE).strip()
        if part:
            cleaned.append(part)
    joiner = "，" if re.search(r"[\u4e00-\u9fff]", str(text or "")) else ", "
    return joiner.join(_dedupe_prompt_items(cleaned)).strip()


def _clean_positive_constraint_text(text: str) -> str:
    cleaned = str(text or "").strip(" \t\r\n，,。.;；:：、")
    if not cleaned or _is_negative_prompt_fragment(cleaned):
        return ""
    if VAGUE_POSITIVE_RE.search(cleaned):
        return ""
    if UNCERTAIN_POSITIVE_RE.search(cleaned):
        return ""
    if AMBIGUOUS_ALTERNATIVE_RE.search(cleaned) and not any(allowed in cleaned for allowed in ALLOWED_POSITIVE_ALTERNATIVES):
        return ""
    if UNSEEN_BODY_PART_RE.search(cleaned) and re.search(r"画面外|裁切|遮挡|挡住|覆盖|遮住|不可见|未见|无可见", cleaned):
        return ""
    return cleaned


def _is_negative_or_unseen_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    return any(
        marker in normalized
        for marker in (
            "negative",
            "负面",
            "avoid",
            "禁止",
            "不要",
            "uncertain",
            "不确定",
        )
    )


def _is_negative_prompt_fragment(text: str) -> bool:
    return bool(getattr(_prompt_optimizer, "_is_negative_prompt_fragment")(str(text or "")))


def _clean_negative_prompt_text(text: str) -> str:
    parts = [part.strip() for part in re.split(r"[，,；;。\n/|]+", str(text or "")) if part.strip()]
    cleaned = []
    for part in parts:
        normalize_negative = getattr(_prompt_optimizer, "normalize_negative_prompt_fragment", None)
        if callable(normalize_negative):
            part = normalize_negative(part)
        if not part:
            continue
        cleaned.append(part)
    return "，".join(_dedupe_prompt_items(cleaned)).strip()


def _clean_flat_structured_prompt(source: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    negative_items: list[str] = []
    for key, value in source.items():
        if str(key or "").strip().lower() in {"constraints", "constraint"}:
            positive_constraints: list[str] = []
            for item in _iter_grouped_prompt_strings(value):
                if _is_negative_prompt_fragment(item):
                    cleaned_item = _clean_negative_prompt_text(item)
                    if cleaned_item:
                        negative_items.append(cleaned_item)
                    continue
                cleaned_item = _clean_positive_constraint_text(item)
                if cleaned_item:
                    positive_constraints.append(cleaned_item)
            if positive_constraints:
                cleaned[str(key)] = _dedupe_prompt_items(positive_constraints)
            continue
        if _is_negative_or_unseen_key(key):
            for item in _iter_grouped_prompt_strings(value):
                cleaned_item = _clean_negative_prompt_text(item)
                if cleaned_item:
                    negative_items.append(cleaned_item)
            continue
        cleaned_value = _clean_structured_positive_value(value)
        if isinstance(cleaned_value, list):
            positive_items = []
            for item in cleaned_value:
                if _is_negative_prompt_fragment(str(item)):
                    negative_items.append(_clean_negative_prompt_text(str(item)))
                else:
                    positive_items.append(item)
            cleaned_value = positive_items
        if cleaned_value in ("", None, [], {}):
            continue
        cleaned[str(key)] = cleaned_value
    if negative_items:
        cleaned["negative_prompt"] = _dedupe_prompt_items(negative_items)
    return cleaned


def _clean_grouped_positive_sections(grouped: dict[str, Any]) -> dict[str, Any]:
    def clean_value(value: Any) -> Any:
        if isinstance(value, dict):
            cleaned_dict: dict[str, Any] = {}
            for key, item in value.items():
                cleaned_item = clean_value(item)
                if cleaned_item in ("", None, [], {}):
                    continue
                cleaned_dict[str(key)] = cleaned_item
            return cleaned_dict
        if isinstance(value, list):
            cleaned_list = []
            for item in value:
                cleaned_item = clean_value(item)
                if cleaned_item in ("", None, [], {}):
                    continue
                cleaned_list.append(cleaned_item)
            return cleaned_list
        if isinstance(value, str):
            return _clean_positive_prompt_text(value)
        return value

    cleaned_grouped = copy.deepcopy(grouped)
    for key in GROUPED_DESCRIPTION_KEYS:
        if isinstance(cleaned_grouped.get(key), dict):
            cleaned_grouped[key] = clean_value(cleaned_grouped[key])
    return _prune_grouped_prompt_value(cleaned_grouped)


def _clean_grouped_negative_sections(grouped: dict[str, Any]) -> dict[str, Any]:
    def clean_value(value: Any) -> Any:
        if isinstance(value, dict):
            cleaned_dict: dict[str, Any] = {}
            for key, item in value.items():
                cleaned_item = clean_value(item)
                if cleaned_item in ("", None, [], {}):
                    continue
                cleaned_dict[str(key)] = cleaned_item
            return cleaned_dict
        if isinstance(value, list):
            cleaned_list = []
            for item in value:
                cleaned_item = clean_value(item)
                if cleaned_item in ("", None, [], {}):
                    continue
                cleaned_list.append(cleaned_item)
            return cleaned_list
        if isinstance(value, str):
            return _clean_negative_prompt_text(value)
        return value

    cleaned_grouped = copy.deepcopy(grouped)
    for key in GROUPED_NEGATIVE_KEYS:
        if isinstance(cleaned_grouped.get(key), dict):
            cleaned_grouped[key] = clean_value(cleaned_grouped[key])
    return _prune_grouped_prompt_value(cleaned_grouped)


def _clean_structured_positive_value(value: Any) -> Any:
    if isinstance(value, dict):
        if _looks_like_grouped_prompt(value):
            normalized = _normalize_grouped_prompt_structure(value)
            return _clean_grouped_negative_sections(_clean_grouped_positive_sections(_prune_grouped_prompt_value(normalized)))
        cleaned_dict: dict[str, Any] = {}
        for key, item in value.items():
            cleaned_item = _clean_negative_prompt_text(item) if _is_negative_or_unseen_key(str(key)) else _clean_structured_positive_value(item)
            if cleaned_item in ("", None, [], {}):
                continue
            cleaned_dict[str(key)] = cleaned_item
        return cleaned_dict
    if isinstance(value, list):
        cleaned_list = []
        for item in value:
            cleaned_item = _clean_structured_positive_value(item)
            if cleaned_item in ("", None, [], {}):
                continue
            cleaned_list.append(cleaned_item)
        return cleaned_list
    if isinstance(value, str):
        return _clean_positive_prompt_text(value)
    return value


def _iter_grouped_prompt_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        items: list[str] = []
        for nested in value.values():
            items.extend(_iter_grouped_prompt_strings(nested))
        return items
    if isinstance(value, (list, tuple)):
        items: list[str] = []
        for nested in value:
            items.extend(_iter_grouped_prompt_strings(nested))
        return items
    text = str(value or "").strip()
    return [text] if text else []


def _dedupe_prompt_items(values: list[str]) -> list[str]:
    items: list[str] = []
    keys: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip(" \t\r\n，,。.;；:：、")
        if len(cleaned) < 2:
            continue
        key = re.sub(r"[\s，,。.;；:：、/|()（）【】\[\]{}\"'“”‘’]+", "", cleaned).lower()
        if not key or key in keys:
            continue
        keys.add(key)
        items.append(cleaned)
    return items


def _grouped_section(value: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in value:
            return value.get(key)
    return {}


def _grouped_prompt_plain_text(grouped: dict[str, Any]) -> str:
    description = _grouped_section(grouped, GROUPED_DESCRIPTION_KEYS)
    return "，".join(_dedupe_prompt_items(_iter_grouped_prompt_strings(description))).strip()


def _grouped_negative_prompt(grouped: dict[str, Any]) -> str:
    negative = _grouped_section(grouped, GROUPED_NEGATIVE_KEYS)
    return _clean_negative_prompt_text("，".join(_dedupe_prompt_items(_iter_grouped_prompt_strings(negative))).strip())


def _grouped_prompt_richness(text: str) -> int:
    parts = [part.strip() for part in re.split(r"[，,；;、\n]+", str(text or "")) if part.strip()]
    return len(_dedupe_prompt_items(parts))


def _parse_grouped_interrogate_json(parsed_json: dict[str, Any]) -> dict[str, Any] | None:
    structured_zh = parsed_json.get("structured_prompt") or parsed_json.get("structured_prompt_zh")
    if not _looks_like_grouped_prompt(structured_zh):
        return None
    grouped_zh = _clean_grouped_negative_sections(_clean_grouped_positive_sections(_prune_grouped_prompt_value(_normalize_grouped_prompt_structure(structured_zh))))
    grouped_plain = _grouped_prompt_plain_text(grouped_zh)
    prompt = str(
        parsed_json.get("keyword_prompt")
        or parsed_json.get("prompt_zh")
        or parsed_json.get("chinese_prompt")
        or grouped_plain
        or ""
    ).strip()
    prompt = _clean_positive_prompt_text(prompt) or grouped_plain
    if grouped_plain and _grouped_prompt_richness(grouped_plain) > _grouped_prompt_richness(prompt):
        prompt = grouped_plain
    result: dict[str, Any] = {
        "prompt": prompt,
        "structured_prompt": grouped_zh,
        "structured_prompt_json": json.dumps(grouped_zh, ensure_ascii=False, indent=2),
    }
    negative = _grouped_negative_prompt(grouped_zh)
    if negative:
        result["negative_prompt"] = negative
    english = str(
        parsed_json.get("english_prompt")
        or parsed_json.get("prompt_en")
        or parsed_json.get("english")
        or ""
    ).strip()
    if english:
        result["prompt_en"] = english
    structured_en = parsed_json.get("structured_prompt_en") or parsed_json.get("structured_prompt_english")
    if _looks_like_grouped_prompt(structured_en):
        grouped_en = _clean_grouped_negative_sections(_clean_grouped_positive_sections(_prune_grouped_prompt_value(_normalize_grouped_prompt_structure(structured_en))))
        result["structured_prompt_en"] = grouped_en
        result["structured_prompt_json_en"] = json.dumps(grouped_en, ensure_ascii=False, indent=2)
    return {key: value for key, value in result.items() if value not in ("", None, [], {})}


def _parse_structured_interrogate_text(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    parsed_json = _extract_json_object(raw) or {}
    if not parsed_json and '"keyword_prompt"' in raw:
        keyword_fallback = _extract_json_string_field(raw, "keyword_prompt")
        english_fallback = _extract_json_string_field(raw, "english_prompt")
        structured_zh = _extract_near_json_structured_fields(raw, "structured_prompt")
        structured_en = _extract_near_json_structured_fields(raw, "structured_prompt_en")
        if structured_zh:
            parsed = parse_prompt_optimizer_output(
                json.dumps(
                    {"keyword_prompt": keyword_fallback, "structured_prompt": structured_zh},
                    ensure_ascii=False,
                ),
                "",
            )
            result = {
                "prompt": parsed.get("optimized_prompt") or keyword_fallback,
                "negative_prompt": parsed.get("negative_prompt"),
                "structured_prompt": parsed.get("structured_prompt"),
                "structured_prompt_json": parsed.get("structured_prompt_json"),
            }
        else:
            result = {"prompt": keyword_fallback}
        if structured_en:
            parsed_en = parse_prompt_optimizer_output(
                json.dumps(
                    {"keyword_prompt": english_fallback or keyword_fallback, "structured_prompt": structured_en},
                    ensure_ascii=False,
                ),
                english_fallback or "",
            )
            if parsed_en.get("optimized_prompt"):
                result["prompt_en"] = parsed_en.get("optimized_prompt")
            if parsed_en.get("structured_prompt"):
                result["structured_prompt_en"] = parsed_en.get("structured_prompt")
            if parsed_en.get("structured_prompt_json"):
                result["structured_prompt_json_en"] = parsed_en.get("structured_prompt_json")
        elif english_fallback:
            result["prompt_en"] = english_fallback
        return {key: value for key, value in result.items() if value}
    grouped = _parse_grouped_interrogate_json(parsed_json) if isinstance(parsed_json, dict) else None
    if grouped:
        return grouped
    structured_zh = parsed_json.get("structured_prompt") or parsed_json.get("structured_prompt_zh")
    if isinstance(structured_zh, dict):
        structured_zh = _clean_structured_positive_value(structured_zh) if _looks_like_grouped_prompt(structured_zh) else _clean_flat_structured_prompt(structured_zh)
        zh_payload = {
            "keyword_prompt": parsed_json.get("keyword_prompt") or parsed_json.get("prompt_zh") or "",
            "structured_prompt": structured_zh,
        }
        parsed = parse_prompt_optimizer_output(json.dumps(zh_payload, ensure_ascii=False), "")
    else:
        parsed = parse_prompt_optimizer_output(raw, "")
    keyword_prompt = str(
        parsed.get("optimized_prompt")
        or parsed_json.get("keyword_prompt")
        or parsed_json.get("positive_prompt")
        or parsed_json.get("prompt_zh")
        or parsed_json.get("chinese_prompt")
        or ""
    ).strip()
    keyword_prompt = _clean_positive_prompt_text(keyword_prompt)
    result: dict[str, Any] = {
        "prompt": keyword_prompt,
        "negative_prompt": parsed.get("negative_prompt"),
        "structured_prompt": parsed.get("structured_prompt"),
        "structured_prompt_json": parsed.get("structured_prompt_json"),
    }
    english = str(
        parsed_json.get("english_prompt")
        or parsed_json.get("prompt_en")
        or parsed_json.get("english")
        or ""
    ).strip()
    if english:
        result["prompt_en"] = english
    structured_en = parsed_json.get("structured_prompt_en") or parsed_json.get("structured_prompt_english")
    if not isinstance(structured_en, dict):
        structured_en = _extract_near_json_structured_fields(raw, "structured_prompt_en")
    if isinstance(structured_en, dict):
        structured_en = _clean_structured_positive_value(structured_en) if _looks_like_grouped_prompt(structured_en) else _clean_flat_structured_prompt(structured_en)
        en_payload = {
            "keyword_prompt": english or str(parsed_json.get("keyword_prompt") or "").strip(),
            "structured_prompt": structured_en,
        }
        parsed_en = parse_prompt_optimizer_output(json.dumps(en_payload, ensure_ascii=False), english or "")
        if parsed_en.get("optimized_prompt"):
            result["prompt_en"] = parsed_en.get("optimized_prompt")
        if parsed_en.get("structured_prompt"):
            result["structured_prompt_en"] = parsed_en.get("structured_prompt")
        if parsed_en.get("structured_prompt_json"):
            result["structured_prompt_json_en"] = parsed_en.get("structured_prompt_json")
    return {key: value for key, value in result.items() if value}


def _expert_observation_from_text(raw_text: str, spec: dict[str, str]) -> dict[str, Any]:
    parsed = _extract_json_object(raw_text)
    if not isinstance(parsed, dict):
        summary = str(raw_text or "").strip()
        return _clamp_expert_result_text({
            "id": spec["id"],
            "label": spec["label"],
            "summary": summary[:1200],
            "fields": {},
            "observations": [summary[:1200]] if summary else [],
            "uncertain": [],
            "negative_constraints": [],
            "confidence": 0.0,
            "raw": raw_text,
        })
    fields = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
    observations = parsed.get("observations") if isinstance(parsed.get("observations"), list) else []
    uncertain = parsed.get("uncertain") if isinstance(parsed.get("uncertain"), list) else []
    raw_negative = parsed.get("negative_constraints") if isinstance(parsed.get("negative_constraints"), list) else []
    negative = []
    for item in raw_negative:
        cleaned_negative = _clean_negative_prompt_text(str(item))
        if cleaned_negative:
            negative.extend(_iter_grouped_prompt_strings(cleaned_negative))
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    return _clamp_expert_result_text({
        "id": str(parsed.get("id") or spec["id"]).strip() or spec["id"],
        "label": str(parsed.get("label") or spec["label"]).strip() or spec["label"],
        "summary": str(parsed.get("summary") or "").strip(),
        "fields": {str(key): value for key, value in fields.items() if str(value).strip()},
        "observations": [str(item).strip() for item in observations if str(item).strip()],
        "uncertain": [str(item).strip() for item in uncertain if str(item).strip()],
        "negative_constraints": _dedupe_prompt_items([str(item).strip() for item in negative if str(item).strip()]),
        "confidence": max(0.0, min(confidence, 1.0)),
        "raw": raw_text,
    })


def _expert_observation_from_markdown(markdown: str, spec: dict[str, str]) -> dict[str, Any]:
    """Parse a compact Markdown expert note into the normal expert result shape."""
    fields: dict[str, str] = {}
    observations: list[str] = []
    negative: list[str] = []
    for raw_line in str(markdown or "").splitlines():
        line = raw_line.strip().lstrip("-*").strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([^:：]{1,16})\s*[:：]\s*(.+)$", line)
        if not match:
            observations.append(line)
            continue
        key = match.group(1).strip()
        value = match.group(2).strip()
        if key in {"负面", "负面提示词", "规避", "negative", "Negative"}:
            cleaned_negative = _clean_negative_prompt_text(value)
            negative.extend(
                item.strip()
                for item in re.split(r"[,，、/]+", cleaned_negative)
                if item.strip()
            )
            continue
        fields[key] = value
    summary = "，".join(_dedupe_prompt_items(_iter_grouped_prompt_strings(fields))) or "，".join(observations)
    return _clamp_expert_result_text(
        {
            "id": spec["id"],
            "label": spec["label"],
            "summary": _clip_expert_text(summary, 45),
            "fields": fields,
            "observations": observations,
            "uncertain": [],
            "negative_constraints": _dedupe_prompt_items(negative),
            "confidence": 0.8 if fields or observations else 0.0,
            "raw": markdown,
        }
    )


def _clip_expert_text(value: Any, limit: int = 360) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _consume_text_budget(value: Any, remaining: int) -> tuple[str, int]:
    text = str(value or "").strip()
    if not text or remaining <= 0:
        return "", max(0, remaining)
    if len(text) <= remaining:
        return text, remaining - len(text)
    if remaining == 1:
        return "…", 0
    return text[: remaining - 1].rstrip() + "…", 0


def _clamp_expert_result_text(item: dict[str, Any], max_chars: int = 100) -> dict[str, Any]:
    """Limit user-visible text for one expert so small models cannot ramble."""
    clamped = dict(item)
    remaining = max(0, int(max_chars or 100))
    summary, remaining = _consume_text_budget(clamped.get("summary"), min(remaining, 45))
    clamped["summary"] = summary
    remaining = max(0, int(max_chars or 100) - len(summary))

    fields = clamped.get("fields") if isinstance(clamped.get("fields"), dict) else {}
    limited_fields: dict[str, str] = {}
    for key, value in fields.items():
        clipped, remaining = _consume_text_budget(value, remaining)
        if clipped:
            limited_fields[str(key)] = clipped
        if remaining <= 0:
            break
    clamped["fields"] = limited_fields

    observations: list[str] = []
    for value in clamped.get("observations") or []:
        clipped, remaining = _consume_text_budget(value, remaining)
        if clipped:
            observations.append(clipped)
        if remaining <= 0:
            break
    clamped["observations"] = observations

    clamped["uncertain"] = [_clip_expert_text(value, 60) for value in (clamped.get("uncertain") or [])[:2]]
    clamped["negative_constraints"] = [_clip_expert_text(value, 40) for value in (clamped.get("negative_constraints") or [])[:2]]
    return clamped


def _build_expert_merge_prompt(expert_results: list[dict[str, Any]]) -> str:
    compact_results = []
    for item in expert_results:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        compact_results.append(
            {
                "id": item.get("id"),
                "label": item.get("label"),
                "summary": _clip_expert_text(item.get("summary"), 260),
                "fields": {str(key): _clip_expert_text(value, 320) for key, value in fields.items()},
                "observations": [_clip_expert_text(value, 220) for value in (item.get("observations") or [])[:8]],
                "uncertain": [_clip_expert_text(value, 180) for value in (item.get("uncertain") or [])[:5]],
                "negative_constraints": [_clip_expert_text(value, 180) for value in (item.get("negative_constraints") or [])[:5]],
                "confidence": item.get("confidence"),
            }
        )
    return EXPERT_IMAGE_MERGE_TEMPLATE.replace(
        "{expert_observations}",
        json.dumps(compact_results, ensure_ascii=False, separators=(",", ":")),
    )


def _compact_expert_results_for_review(expert_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact_results: list[dict[str, Any]] = []
    for item in expert_results:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        compact_results.append(
            {
                "id": item.get("id"),
                "label": item.get("label"),
                "summary": _clip_expert_text(item.get("summary"), 220),
                "fields": {str(key): _clip_expert_text(value, 260) for key, value in fields.items()},
                "observations": [_clip_expert_text(value, 160) for value in (item.get("observations") or [])[:5]],
                "uncertain": [_clip_expert_text(value, 120) for value in (item.get("uncertain") or [])[:3]],
                "negative_constraints": [_clip_expert_text(value, 120) for value in (item.get("negative_constraints") or [])[:3]],
                "confidence": item.get("confidence"),
            }
        )
    return compact_results


def _build_expert_review_prompt(expert_results: list[dict[str, Any]]) -> str:
    return EXPERT_IMAGE_REVIEW_TEMPLATE.replace(
        "{expert_observations}",
        json.dumps(_compact_expert_results_for_review(expert_results), ensure_ascii=False, separators=(",", ":")),
    )


def _expert_review_from_text(raw_text: str, expert_results: list[dict[str, Any]]) -> dict[str, Any]:
    parsed = _extract_json_object(raw_text) or {}
    if not isinstance(parsed, dict):
        parsed = {}
    known_labels = {str(item.get("id") or ""): str(item.get("label") or "") for item in expert_results if isinstance(item, dict)}
    reviews: list[dict[str, Any]] = []
    for item in parsed.get("reviews") or []:
        if not isinstance(item, dict):
            continue
        expert_id = str(item.get("id") or "").strip()
        if not expert_id:
            continue
        def score(key: str) -> float:
            try:
                return max(0.0, min(float(item.get(key, 0.0)), 1.0))
            except Exception:
                return 0.0
        detail_score = score("detail_score")
        factual_score = score("factual_score")
        boundary_score = score("boundary_score")
        unsupported = [str(value).strip() for value in (item.get("unsupported") or []) if str(value).strip()]
        missing = [str(value).strip() for value in (item.get("missing") or []) if str(value).strip()]
        passed = bool(item.get("passed"))
        if detail_score < 0.72 or factual_score < 0.72 or boundary_score < 0.72 or unsupported:
            passed = False
        reviews.append(
            {
                "id": expert_id,
                "label": str(item.get("label") or known_labels.get(expert_id) or expert_id).strip(),
                "passed": passed,
                "detail_score": detail_score,
                "factual_score": factual_score,
                "boundary_score": boundary_score,
                "missing": missing,
                "unsupported": unsupported,
                "retry_instruction": _clip_expert_text(item.get("retry_instruction"), 260),
            }
        )
    retry_ids = []
    for expert_id in parsed.get("retry_expert_ids") or []:
        expert_id = str(expert_id or "").strip()
        if expert_id and expert_id not in retry_ids:
            retry_ids.append(expert_id)
    for review in reviews:
        if not review.get("passed") and review["id"] not in retry_ids:
            retry_ids.append(review["id"])
    return {
        "summary": _clip_expert_text(parsed.get("summary"), 360),
        "retry_expert_ids": retry_ids,
        "reviews": reviews,
        "raw": raw_text,
    }


def _expert_retry_instruction(review_report: dict[str, Any], expert_id: str) -> str:
    for review in review_report.get("reviews") or []:
        if str(review.get("id") or "") == expert_id:
            parts = []
            if review.get("missing"):
                parts.append("缺少：" + "；".join(review.get("missing") or []))
            if review.get("unsupported"):
                parts.append("不属实/越界：" + "；".join(review.get("unsupported") or []))
            if review.get("retry_instruction"):
                parts.append("重写要求：" + str(review.get("retry_instruction")))
            return "；".join(parts)
    return ""


def _review_failed_expert_ids(review_report: dict[str, Any], selected_specs: list[dict[str, str]]) -> list[str]:
    selected_ids = {spec["id"] for spec in selected_specs}
    failed: list[str] = []
    for expert_id in review_report.get("retry_expert_ids") or []:
        expert_id = str(expert_id or "").strip()
        if expert_id in selected_ids and expert_id not in failed:
            failed.append(expert_id)
    return failed


def _expert_spec_by_id() -> dict[str, dict[str, str]]:
    return {spec["id"]: spec for spec in IMAGE_INTERROGATE_EXPERTS}


PERSON_EXPERT_IDS = (
    "composition",
    "photography_parameters",
    "color_light",
    "mood_style",
    "body_pose",
    "expression_language",
    "sexual_boundary",
    "clothing_makeup",
    "materials_texture",
)

OBJECT_SCENE_EXPERT_IDS = (
    "composition",
    "photography_parameters",
    "color_light",
    "mood_style",
    "clothing_makeup",
    "materials_texture",
)


def _select_experts_from_global_overview(overview: dict[str, Any] | None) -> list[str]:
    """Choose expert slots after a cheap global pass identifies the image type."""
    overview = overview if isinstance(overview, dict) else {}
    text = "，".join(_iter_grouped_prompt_strings(overview))
    has_person = overview.get("has_person")
    if has_person is None:
        has_person = bool(re.search(r"人物|人像|女性|男性|girl|woman|man|person|face|body", text, flags=re.IGNORECASE))
    selected = PERSON_EXPERT_IDS if has_person else OBJECT_SCENE_EXPERT_IDS
    return [expert_id for expert_id in selected if expert_id in _expert_spec_by_id()]


def _global_expert_overview_from_text(raw_text: str) -> dict[str, Any]:
    parsed = _extract_json_object(raw_text) or {}
    if not isinstance(parsed, dict):
        return {}
    spec_by_id = _expert_spec_by_id()
    raw_selected = parsed.get("recommended_experts")
    selected: list[str] = []
    if isinstance(raw_selected, list):
        for item in raw_selected:
            expert_id = str(item or "").strip()
            if expert_id in spec_by_id and expert_id not in selected:
                selected.append(expert_id)
    if not selected:
        selected = _select_experts_from_global_overview(parsed)
    if not selected:
        selected = [spec["id"] for spec in IMAGE_INTERROGATE_EXPERTS]
    if parsed.get("has_person") is True:
        selected = [expert_id for expert_id in PERSON_EXPERT_IDS if expert_id in spec_by_id]
    parsed["recommended_experts"] = selected
    return parsed


def _expert_specs_for_overview(overview: dict[str, Any]) -> list[dict[str, str]]:
    spec_by_id = _expert_spec_by_id()
    selected_ids = overview.get("recommended_experts") if isinstance(overview, dict) else []
    selected = [spec_by_id[expert_id] for expert_id in selected_ids if expert_id in spec_by_id]
    return selected or list(IMAGE_INTERROGATE_EXPERTS)


def _complete_expert_results(expert_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one ordered entry for every configured expert, preserving valid observations."""
    by_id: dict[str, dict[str, Any]] = {}
    for item in expert_results:
        if not isinstance(item, dict):
            continue
        expert_id = str(item.get("id") or "").strip()
        if not expert_id or expert_id in by_id:
            continue
        by_id[expert_id] = item

    completed: list[dict[str, Any]] = []
    for spec in IMAGE_INTERROGATE_EXPERTS:
        item = by_id.get(spec["id"])
        if item is not None:
            item.setdefault("id", spec["id"])
            item.setdefault("label", spec["label"])
            completed.append(_clamp_expert_result_text(item))
            continue
        completed.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "summary": "模型未返回该专家维度，已保留专家席位",
                "fields": {},
                "observations": [],
                "uncertain": ["模型未返回该专家维度"],
                "negative_constraints": [],
                "confidence": 0.0,
                "raw": "",
                "missing": True,
            }
        )
    return completed


def _coerce_evidence_record(value: Any, fallback_evidence: str = "", fallback_confidence: float = 0.8) -> dict[str, Any]:
    if isinstance(value, dict) and any(key in value for key in ("value", "evidence", "confidence", "allow_positive")):
        record = dict(value)
        record.setdefault("evidence", fallback_evidence or "系统归一化证据")
        record.setdefault("confidence", fallback_confidence)
        record.setdefault("allow_positive", True)
        return record
    return {
        "value": value,
        "evidence": fallback_evidence or "系统归一化证据",
        "confidence": fallback_confidence,
        "allow_positive": True,
    }


def _normalize_visual_evidence(raw_evidence: Any) -> dict[str, Any] | None:
    """Normalize loose model evidence into the keyed evidence table used by quality gates."""
    if isinstance(raw_evidence, dict):
        if any(key in raw_evidence for key in REQUIRED_EVIDENCE_KEYS):
            normalized: dict[str, Any] = {}
            for key in REQUIRED_EVIDENCE_KEYS:
                if key in raw_evidence:
                    normalized[key] = _coerce_evidence_record(raw_evidence[key], key)
            return normalized or None
        value = raw_evidence.get("value")
        if isinstance(value, dict):
            return _normalize_visual_evidence([raw_evidence])
        return None

    if not isinstance(raw_evidence, list):
        return None

    normalized: dict[str, Any] = {}
    for item in raw_evidence:
        if not isinstance(item, dict):
            continue
        confidence = item.get("confidence")
        try:
            fallback_confidence = float(confidence)
        except (TypeError, ValueError):
            fallback_confidence = 0.8
        fallback_evidence = str(item.get("evidence") or "模型宽松证据").strip()
        value = item.get("value")
        if isinstance(value, dict):
            for key in REQUIRED_EVIDENCE_KEYS:
                if key in value and key not in normalized:
                    normalized[key] = _coerce_evidence_record(
                        value[key],
                        fallback_evidence or key,
                        fallback_confidence,
                    )
            continue
        evidence_key = str(item.get("key") or item.get("id") or item.get("field") or item.get("evidence") or "").strip()
        if evidence_key in REQUIRED_EVIDENCE_KEYS and evidence_key not in normalized:
            normalized[evidence_key] = _coerce_evidence_record(
                value,
                fallback_evidence or evidence_key,
                fallback_confidence,
            )
    return normalized or None


def _evidence_value_text(evidence_item: Any) -> str:
    if isinstance(evidence_item, dict):
        return "，".join(_iter_grouped_prompt_strings(evidence_item.get("value")))
    return "，".join(_iter_grouped_prompt_strings(evidence_item))


def _backfill_expert_results_from_visual_evidence(
    expert_results: list[dict[str, Any]],
    visual_evidence: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Use normalized evidence to fill expert slots that the model omitted."""
    if not isinstance(visual_evidence, dict) or not visual_evidence:
        return expert_results
    seen = {str(item.get("id") or "").strip() for item in expert_results if isinstance(item, dict)}
    filled = list(expert_results)
    sexual_text = _evidence_value_text(visual_evidence.get("nsfw_visible_evidence"))
    if sexual_text and "sexual_boundary" not in seen:
        filled.append(
            _clamp_expert_result_text(
            {
                "id": "sexual_boundary",
                "label": "性内容边界专家",
                "summary": _clip_expert_text(sexual_text, 220),
                "fields": {"可见事实": sexual_text},
                "observations": [_clip_expert_text(sexual_text, 220)],
                "uncertain": [],
                "negative_constraints": [],
                "confidence": 0.8,
                "raw": sexual_text,
                "backfilled": True,
            }
            )
        )
    return filled


def _fast_expert_results_from_json(parsed_json: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = parsed_json.get("expert_observations")
    results: list[dict[str, Any]] = []
    spec_by_id = _expert_spec_by_id()
    if isinstance(raw_items, dict):
        for expert_id, value in raw_items.items():
            expert_id = str(expert_id or "").strip()
            spec = spec_by_id.get(expert_id)
            if not spec:
                continue
            fields = value if isinstance(value, dict) else {"观察": value}
            text = "，".join(_dedupe_prompt_items(_iter_grouped_prompt_strings(fields)))
            results.append(
                _clamp_expert_result_text(
                    {
                        "id": spec["id"],
                        "label": spec["label"],
                        "summary": _clip_expert_text(text, 45),
                        "fields": {str(key): field_value for key, field_value in fields.items() if str(field_value).strip()},
                        "observations": [text] if text else [],
                        "uncertain": [],
                        "negative_constraints": [],
                        "confidence": 0.8 if text else 0.0,
                        "raw": json.dumps(value, ensure_ascii=False),
                    }
                )
            )
    if isinstance(raw_items, list):
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            expert_id = str(raw.get("id") or "").strip()
            spec = spec_by_id.get(expert_id) or {
                "id": expert_id or "unknown",
                "label": str(raw.get("label") or "专家观察"),
            }
            results.append(_expert_observation_from_text(json.dumps(raw, ensure_ascii=False), spec))

    structured = parsed_json.get("structured_prompt")
    description = _grouped_section(structured, GROUPED_DESCRIPTION_KEYS) if isinstance(structured, dict) else {}
    domain_map = {
        "composition": ("构图镜头", "构图镜头专家"),
        "photography_parameters": ("摄影参数", "摄影参数专家"),
        "color_light": ("颜色光影", "颜色光影专家"),
        "mood_style": ("氛围风格", "氛围风格专家"),
        "body_pose": ("肢体动作", "肢体动作专家"),
        "expression_language": ("表情语言", "表情语言专家"),
        "sexual_boundary": ("性内容边界", "性内容边界专家"),
        "clothing_makeup": ("服装妆容", "服装妆容专家"),
        "materials_texture": ("材质纹理", "材质纹理专家"),
    }
    seen_ids = {item.get("id") for item in results}
    for expert_id, (section_key, label) in domain_map.items():
        if expert_id in seen_ids:
            continue
        value = description.get(section_key) if isinstance(description, dict) else None
        text = "，".join(_dedupe_prompt_items(_iter_grouped_prompt_strings(value)))
        if not text:
            continue
        results.append(
            {
                "id": expert_id,
                "label": label,
                "summary": _clip_expert_text(text, 220),
                "fields": {section_key: text},
                "observations": [_clip_expert_text(text, 220)],
                "uncertain": [],
                "negative_constraints": [],
                "confidence": 0.75,
                "raw": text,
            }
        )
    return _complete_expert_results(results)


def _fast_expert_results_from_structured(structured_prompt: Any) -> list[dict[str, Any]]:
    if not isinstance(structured_prompt, dict):
        return []
    return _fast_expert_results_from_json({"structured_prompt": structured_prompt})


EXPERT_STRUCTURED_SECTION_BY_ID = {
    "composition": "构图镜头",
    "photography_parameters": "摄影参数",
    "color_light": "颜色光影",
    "mood_style": "氛围风格",
    "body_pose": "肢体动作",
    "expression_language": "表情语言",
    "sexual_boundary": "性内容边界",
    "clothing_makeup": "服装妆容",
    "materials_texture": "材质纹理",
}


def _fallback_expert_structured_prompt(prompt: str, negative_prompt: str, expert_results: list[dict[str, Any]]) -> dict[str, Any]:
    description: dict[str, Any] = {}
    negative_items: list[str] = []
    for item in expert_results:
        if not isinstance(item, dict):
            continue
        if item.get("missing"):
            continue
        expert_id = str(item.get("id") or "").strip()
        section_key = EXPERT_STRUCTURED_SECTION_BY_ID.get(expert_id) or str(item.get("label") or expert_id or "专家观察").strip() or "专家观察"
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        observations = [str(value).strip() for value in (item.get("observations") or []) if str(value).strip()]
        summary = str(item.get("summary") or "").strip()
        section = description.setdefault(section_key, {})
        if not isinstance(section, dict):
            section = {}
            description[section_key] = section
        if fields:
            section.update({str(key): value for key, value in fields.items() if str(value).strip()})
        if observations:
            section["观察"] = observations
        elif summary:
            section["观察"] = [summary]
        for value in item.get("negative_constraints") or []:
            cleaned = _clean_negative_prompt_text(str(value))
            if cleaned:
                negative_items.extend(_iter_grouped_prompt_strings(cleaned))
    if not description and str(prompt or "").strip():
        description["复刻约束"] = {"摘要": str(prompt).strip()}
    if negative_prompt:
        negative_items.extend(_iter_grouped_prompt_strings(_clean_negative_prompt_text(negative_prompt)))
    return _prune_grouped_prompt_value(
        {
            "画面描述": description,
            "负面提示词": {"专家负面": _dedupe_prompt_items(negative_items)},
        }
    )


def _image_size_for_quality(image_path: str) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(image_path) as img:
            return int(img.width), int(img.height)
    except Exception:
        return None


def _image_metadata_context(image_path: str) -> str:
    size = _image_size_for_quality(image_path)
    if not size:
        return ""
    width, height = size
    if width <= 0 or height <= 0:
        return ""
    orientation = "竖版" if height > width else "横版" if width > height else "正方形"
    ratio = height / width
    return (
        f"\n内部图像元数据：原图宽 {width}px，高 {height}px，方向为{orientation}，"
        f"高宽比约 {ratio:.2f}。构图比例必须以这个元数据为准，不得把竖图写成 1:1。\n"
    )


def _structured_for_quality(result: dict[str, Any]) -> Any:
    structured = result.get("structured_prompt")
    if structured:
        return structured
    raw = result.get("structured_prompt_json")
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return result.get("prompt") or ""


def _attach_reverse_prompt_quality(
    result: dict[str, Any],
    image_path: str,
    expert_results: list[dict[str, Any]] | None = None,
    visual_evidence: dict[str, Any] | None = None,
    require_visual_evidence: bool = False,
) -> dict[str, Any]:
    report = validate_reverse_prompt_quality(
        _structured_for_quality(result),
        image_size=_image_size_for_quality(image_path),
        expert_results=expert_results,
        visual_evidence=visual_evidence,
        require_visual_evidence=require_visual_evidence,
    )
    result["reverse_prompt_quality"] = report
    expert_data = result.get("expert_interrogate")
    if isinstance(expert_data, dict):
        expert_data["quality"] = report
    return result


def extract_interrogate_result(history_entry: dict[str, Any]) -> dict[str, Any]:
    """Extract prompt candidates from a ComfyUI interrogation history entry."""
    outputs = history_entry.get("outputs", {}) if isinstance(history_entry, dict) else {}
    wd14 = _text_output(outputs, "3") or _tag_output(outputs, "2")
    structured_raw = _text_output(outputs, "6")
    structured = _parse_structured_interrogate_text(structured_raw)
    structured_prompt = str(structured.get("prompt") or "").strip()
    promptgen = structured_prompt or _clean_promptgen_text(_text_output(outputs, "7"))
    wd14_as_prompt = "" if _is_tag_like_prompt_line(wd14) else wd14
    prompt = promptgen or wd14_as_prompt
    result: dict[str, Any] = {
        "prompt": prompt,
        "promptgen": promptgen,
        "wd14_tags": wd14,
        "structured_raw": structured_raw,
    }
    if promptgen:
        result["prompt_zh"] = promptgen
    if structured.get("prompt_en"):
        result["prompt_en"] = structured["prompt_en"]
    if structured.get("negative_prompt"):
        result["negative_prompt"] = structured["negative_prompt"]
    if structured.get("structured_prompt"):
        result["structured_prompt"] = structured["structured_prompt"]
    if structured.get("structured_prompt_json"):
        result["structured_prompt_json"] = structured["structured_prompt_json"]
    if structured.get("structured_prompt_en"):
        result["structured_prompt_en"] = structured["structured_prompt_en"]
    if structured.get("structured_prompt_json_en"):
        result["structured_prompt_json_en"] = structured["structured_prompt_json_en"]
    return result


def _provider_for_result(result: dict[str, Any]) -> str:
    if result.get("structured_prompt_json") or result.get("structured_raw"):
        return "comfyui-qwen3-vl"
    return "comfyui-wd14"


def run_llm_image_interrogator(
    image_path: str,
    *,
    chat_fn: Callable[..., str] = chat_text,
    timeout: float = 180.0,
    max_new_tokens: int = 3072,
    model: str | None = None,
    compact: bool = False,
    include_quality: bool = False,
) -> dict[str, Any]:
    """Interrogate an image through the resident multimodal LLM service."""
    data_url = image_to_data_url(image_path)
    metadata_context = _image_metadata_context(image_path)
    prompt_template = FAST_IMAGE_INTERROGATE_TEMPLATE if compact else QWEN_IMAGE_INTERROGATE_TEMPLATE
    raw_text = chat_fn(
        [
            {
                "role": "system",
                "content": DIRECT_FINAL_SYSTEM_PROMPT
                + " Return only the requested valid JSON object. Do not output markdown.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_template + metadata_context},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        model=model,
        temperature=0.15,
        max_tokens=max(512, min(int(max_new_tokens or 3072), 4096)),
        timeout=timeout,
        response_format={"type": "json_object"},
    )
    structured = _parse_structured_interrogate_text(raw_text)
    prompt = str(structured.get("prompt") or "").strip()
    if not prompt:
        raise RuntimeError("LLM image interrogation completed without text output")
    if prompt.startswith("{") and "keyword_prompt" in prompt:
        raise RuntimeError("LLM image interrogation returned malformed structured JSON")
    result: dict[str, Any] = {
        "ok": True,
        "provider": llm_provider_name(model, vision=True),
        "prompt_id": "",
        "prompt": prompt,
        "promptgen": prompt,
        "wd14_tags": "",
        "structured_raw": raw_text,
        "prompt_zh": prompt,
    }
    for key in (
        "prompt_en",
        "structured_prompt",
        "structured_prompt_json",
        "negative_prompt",
        "structured_prompt_en",
        "structured_prompt_json_en",
    ):
        if structured.get(key):
            result[key] = structured[key]
    return _attach_reverse_prompt_quality(result, image_path) if include_quality else result


def run_llm_expert_image_interrogator(
    image_path: str,
    *,
    chat_fn: Callable[..., str] = chat_text,
    timeout: float = 300.0,
    max_new_tokens: int = 3072,
    model: str | None = None,
    single_pass: bool = False,
    include_quality: bool = False,
) -> dict[str, Any]:
    """Run dimension-specific image interrogation experts and merge their findings."""
    data_url = image_to_data_url(image_path)
    metadata_context = _image_metadata_context(image_path)
    if single_pass:
        raw_text = chat_fn(
            [
                {
                    "role": "system",
                    "content": DIRECT_FINAL_SYSTEM_PROMPT
                    + " Return only the requested valid JSON object. Do not output markdown.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE + metadata_context},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            model=model,
            temperature=0.1,
            max_tokens=max(768, min(int(max_new_tokens or 1024), 2048)),
            timeout=timeout,
            response_format={"type": "json_object"},
        )
        parsed_json = _extract_json_object(raw_text) or {}
        visual_evidence = _normalize_visual_evidence(parsed_json.get("visual_evidence"))
        structured = _parse_structured_interrogate_text(raw_text)
        prompt = str(parsed_json.get("keyword_prompt") or structured.get("prompt") or "").strip()
        prompt = _clean_positive_prompt_text(prompt)
        if not prompt:
            raise RuntimeError("Expert image interrogation completed without merged text output")
        provider = llm_provider_name(model, vision=True)
        expert_results = _fast_expert_results_from_json(parsed_json) if isinstance(parsed_json, dict) else []
        expert_results = _backfill_expert_results_from_visual_evidence(expert_results, visual_evidence)
        if len(expert_results) < 4:
            structured_experts = _fast_expert_results_from_structured(structured.get("structured_prompt"))
            seen_ids = {item.get("id") for item in expert_results}
            expert_results.extend([item for item in structured_experts if item.get("id") not in seen_ids])
            expert_results = _backfill_expert_results_from_visual_evidence(expert_results, visual_evidence)
        result: dict[str, Any] = {
            "ok": True,
            "provider": f"{provider}-expert-fast",
            "prompt_id": "",
            "prompt": prompt,
            "promptgen": prompt,
            "wd14_tags": "",
            "structured_raw": raw_text,
            "prompt_zh": prompt,
            "expert_interrogate": {
                "enabled": True,
                "provider": provider,
                "mode": "single_pass",
                "experts": expert_results,
                "merged_raw": raw_text,
            },
        }
        for key in (
            "prompt_en",
            "structured_prompt",
            "structured_prompt_json",
            "negative_prompt",
            "structured_prompt_en",
            "structured_prompt_json_en",
        ):
            if structured.get(key):
                result[key] = structured[key]
        if not result.get("structured_prompt_json") or '"画面描述"' not in str(result.get("structured_prompt_json") or ""):
            fallback_structured = _fallback_expert_structured_prompt(
                prompt,
                str(result.get("negative_prompt") or ""),
                expert_results,
            )
            result["structured_prompt"] = fallback_structured
            result["structured_prompt_json"] = json.dumps(fallback_structured, ensure_ascii=False, indent=2)
            structured_prompt_text = _grouped_prompt_plain_text(fallback_structured)
            if structured_prompt_text:
                result["prompt"] = structured_prompt_text
                result["promptgen"] = result["prompt"]
                result["prompt_zh"] = result["prompt"]
        return _attach_reverse_prompt_quality(
            result,
            image_path,
            expert_results,
            visual_evidence=visual_evidence,
            require_visual_evidence=True,
        ) if include_quality else result

    overview_timeout = None
    expert_timeout = None
    review_timeout = None
    merge_timeout = None
    if timeout is not None:
        total_timeout = max(30.0, float(timeout or 720.0))
        overview_timeout = max(20.0, total_timeout * 0.12)
    raw_overview = chat_fn(
        [
            {
                "role": "system",
                "content": DIRECT_FINAL_SYSTEM_PROMPT
                + " Return only the requested valid JSON object. Do not output markdown.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": GLOBAL_EXPERT_OVERVIEW_TEMPLATE + metadata_context},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        model=model,
        temperature=0.05,
        max_tokens=512,
        timeout=overview_timeout,
        response_format={"type": "json_object"},
    )
    expert_overview = _global_expert_overview_from_text(raw_overview)
    selected_specs = _expert_specs_for_overview(expert_overview)
    if timeout is not None:
        remaining_timeout = max(30.0, float(timeout or 720.0) - float(overview_timeout or 0.0))
        expert_timeout = max(30.0, remaining_timeout / max(1, len(selected_specs) + 3))
        review_timeout = max(30.0, expert_timeout)
        merge_timeout = max(45.0, expert_timeout)

    expert_results: list[dict[str, Any]] = []
    for spec in selected_specs:
        prompt = (
            EXPERT_IMAGE_INTERROGATE_TEMPLATE
            .replace("{expert_id}", spec["id"])
            .replace("{expert_label}", spec["label"])
            .replace("{expert_instruction}", spec["instruction"])
            .replace("{{", "{")
            .replace("}}", "}")
        )
        raw_expert = chat_fn(
            [
                {
                    "role": "system",
                    "content": DIRECT_FINAL_SYSTEM_PROMPT
                    + " Return only the requested valid JSON object. Do not output markdown.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            model=model,
            temperature=0.1,
            max_tokens=640,
            timeout=expert_timeout,
            response_format={"type": "json_object"},
        )
        expert_results.append(_expert_observation_from_text(raw_expert, spec))

    raw_review = chat_fn(
        [
            {
                "role": "system",
                "content": DIRECT_FINAL_SYSTEM_PROMPT
                + " Return only the requested valid JSON object. Do not output markdown.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _build_expert_review_prompt(expert_results) + metadata_context},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        model=model,
        temperature=0.05,
        max_tokens=1400,
        timeout=review_timeout,
        response_format={"type": "json_object"},
    )
    review_report = _expert_review_from_text(raw_review, expert_results)
    failed_expert_ids = _review_failed_expert_ids(review_report, selected_specs)
    retried_expert_ids: list[str] = []
    if failed_expert_ids:
        spec_by_id = {spec["id"]: spec for spec in selected_specs}
        result_by_id = {str(item.get("id") or ""): item for item in expert_results}
        for expert_id in failed_expert_ids:
            spec = spec_by_id.get(expert_id)
            if not spec:
                continue
            retry_instruction = _expert_retry_instruction(review_report, expert_id)
            base_prompt = (
                EXPERT_IMAGE_INTERROGATE_TEMPLATE
                .replace("{expert_id}", spec["id"])
                .replace("{expert_label}", spec["label"])
                .replace("{expert_instruction}", spec["instruction"])
                .replace("{{", "{")
                .replace("}}", "}")
            )
            retry_prompt = (
                base_prompt
                + "复审专家已打回本专家初稿。必须按复审意见重写，只输出本专家职责范围内的新 JSON。"
                + "复审意见："
                + retry_instruction
                + "。上一版初稿："
                + json.dumps(_compact_expert_results_for_review([result_by_id.get(expert_id, {})]), ensure_ascii=False, separators=(",", ":"))
            )
            raw_retry = chat_fn(
                [
                    {
                        "role": "system",
                        "content": DIRECT_FINAL_SYSTEM_PROMPT
                        + " Return only the requested valid JSON object. Do not output markdown.",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": retry_prompt + metadata_context},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
                model=model,
                temperature=0.08,
                max_tokens=760,
                timeout=expert_timeout,
                response_format={"type": "json_object"},
            )
            revised = _expert_observation_from_text(raw_retry, spec)
            revised["review_retry"] = {
                "from_review": True,
                "instruction": retry_instruction,
            }
            for idx, item in enumerate(expert_results):
                if str(item.get("id") or "") == expert_id:
                    expert_results[idx] = revised
                    break
            else:
                expert_results.append(revised)
            retried_expert_ids.append(expert_id)

    final_review_report = None
    if retried_expert_ids:
        raw_final_review = chat_fn(
            [
                {
                    "role": "system",
                    "content": DIRECT_FINAL_SYSTEM_PROMPT
                    + " Return only the requested valid JSON object. Do not output markdown.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _build_expert_review_prompt(expert_results) + metadata_context},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            model=model,
            temperature=0.05,
            max_tokens=1400,
            timeout=review_timeout,
            response_format={"type": "json_object"},
        )
        final_review_report = _expert_review_from_text(raw_final_review, expert_results)

    merge_prompt = _build_expert_merge_prompt(expert_results)
    raw_merge = chat_fn(
        [
            {
                "role": "system",
                "content": DIRECT_FINAL_SYSTEM_PROMPT
                + " Return only the requested valid JSON object. Do not output markdown.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": merge_prompt + metadata_context},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        model=model,
        temperature=0.1,
        max_tokens=max(1024, min(int(max_new_tokens or 3072), 4096)),
        timeout=merge_timeout,
        response_format={"type": "json_object"},
    )
    structured = _parse_structured_interrogate_text(raw_merge)
    prompt = str(structured.get("prompt") or "").strip()
    if not prompt:
        raise RuntimeError("Expert image interrogation completed without merged text output")
    provider = llm_provider_name(model, vision=True)
    result: dict[str, Any] = {
        "ok": True,
        "provider": f"{provider}-expert",
        "prompt_id": "",
        "prompt": prompt,
        "promptgen": prompt,
        "wd14_tags": "",
        "structured_raw": raw_merge,
        "prompt_zh": prompt,
        "expert_interrogate": {
            "enabled": True,
            "provider": provider,
            "mode": "staged",
            "global_overview": expert_overview,
            "selected_experts": [spec["id"] for spec in selected_specs],
            "expected_expert_count": len(selected_specs),
            "experts": expert_results,
            "review": review_report,
            "review_retry_count": len(retried_expert_ids),
            "review_retry_expert_ids": retried_expert_ids,
            "final_review": final_review_report,
            "merged_raw": raw_merge,
        },
    }
    for key in (
        "prompt_en",
        "structured_prompt",
        "structured_prompt_json",
        "negative_prompt",
        "structured_prompt_en",
        "structured_prompt_json_en",
    ):
        if structured.get(key):
            result[key] = structured[key]
    if not result.get("structured_prompt_json") or '"画面描述"' not in str(result.get("structured_prompt_json") or ""):
        fallback_structured = _fallback_expert_structured_prompt(
            prompt,
            str(result.get("negative_prompt") or ""),
            expert_results,
        )
        result["structured_prompt"] = fallback_structured
        result["structured_prompt_json"] = json.dumps(fallback_structured, ensure_ascii=False, indent=2)
    return _attach_reverse_prompt_quality(result, image_path, expert_results) if include_quality else result


def run_image_interrogator(
    image_filename: str,
    base_url: str,
    comfyui_post: Callable[[str, dict, str | None], dict[str, Any]],
    comfyui_get: Callable[[str, str | None], dict[str, Any]],
    timeout: float = 180.0,
    poll_interval: float = 1.0,
) -> dict[str, Any]:
    """Submit the interrogation workflow to ComfyUI and return prompt text."""
    workflow = build_image_interrogate_workflow(image_filename)
    response = comfyui_post(
        "/prompt",
        {"prompt": copy.deepcopy(workflow), "client_id": f"ez-img-prompt-{uuid.uuid4().hex}"},
        base_url,
    )
    prompt_id = str(response.get("prompt_id") or "")
    if not prompt_id:
        raise RuntimeError("ComfyUI did not return prompt_id for image interrogation")

    deadline = time.time() + float(timeout or 180.0)
    while time.time() < deadline:
        history = comfyui_get(f"/history/{prompt_id}", base_url)
        if isinstance(history, dict) and prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {}) if isinstance(entry, dict) else {}
            if status.get("completed", False):
                result = extract_interrogate_result(entry)
                if result["prompt"]:
                    return {"ok": True, "provider": _provider_for_result(result), "prompt_id": prompt_id, **result}
                raise RuntimeError("ComfyUI image interrogation completed without text output")
            if status.get("status_str") == "error":
                messages = status.get("messages", [])
                raise RuntimeError(str(messages)[:300] if messages else "ComfyUI image interrogation failed")
        time.sleep(max(0.1, float(poll_interval or 1.0)))
    raise TimeoutError("Image interrogation timed out")
