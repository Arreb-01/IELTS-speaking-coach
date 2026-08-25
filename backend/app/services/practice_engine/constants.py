"""练习会话常量：轮次时长上限、限额、阶段名。"""

from datetime import timedelta

# 单轮作答上限（秒）
TURN_MAX_SECONDS = {1: 90, 2: 150, 3: 120}
PART2_PREP_SECONDS = 60

# 沉默提示：用户开始作答后沉默多久触发（前端 VAD 检测并上报）
SILENCE_THRESHOLD_SECONDS = 10

# 题目数量
PART1_QUESTION_COUNT = 4      # 每次练习取 4 题
PART3_QUESTION_COUNT = 4      # 生成 4 道讨论题（含追问）

# Part 3 深度递进：第 n 题的目标深度（1-5）
PART3_DEPTH_PLAN = [2, 3, 4, 5]

# 音频与时长限额
MAX_TURN_AUDIO_BYTES = 6 * 1024 * 1024        # 单轮 ~3 分钟 PCM
MAX_SESSION_AUDIO_BYTES = 60 * 1024 * 1024    # 会话 ~30 分钟
MAX_SESSION_DURATION = timedelta(minutes=35)
RECONNECT_TTL = timedelta(minutes=5)

# 阶段
PHASE_PREPARING = "preparing"      # Part 2 备稿倒计时
PHASE_EXAMINER_ASKS = "examiner_asks"
PHASE_USER_ANSWERS = "user_answers"
PHASE_FINISHED = "finished"

# 考官音色与语速（前端选项 → TTS 参数）
ACCENTS = ("en_female_anna", "en_female_ariana", "en_male_jackson")
SPEEDS = ("slow", "normal", "fast")
