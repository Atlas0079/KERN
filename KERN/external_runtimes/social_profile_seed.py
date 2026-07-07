from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any


WeightedOptions = dict[str, float]


@dataclass(frozen=True)
class InfluenceRule:
	source_field: str
	source_values: tuple[str, ...]
	target_field: str
	multipliers: dict[str, float]
	reason: str

	def matches(self, profile: dict[str, Any]) -> bool:
		return str(profile.get(self.source_field, "")) in self.source_values


PLATFORM_ARCHETYPES: WeightedOptions = {
	"private_social": 0.30,
	"short_video_mass": 0.30,
	"public_discussion": 0.14,
	"lifestyle_discovery": 0.13,
	"interest_community": 0.13,
}

AGE_BANDS: WeightedOptions = {
	"18-24": 0.17,
	"25-34": 0.27,
	"35-44": 0.24,
	"45-54": 0.18,
	"55+": 0.14,
}

AGE_RANGES: dict[str, tuple[int, int]] = {
	"18-24": (18, 24),
	"25-34": (25, 34),
	"35-44": (35, 44),
	"45-54": (45, 54),
	"55+": (55, 72),
}

BASE_WEIGHTS: dict[str, WeightedOptions] = {
	"education": {
		"high_school": 0.18,
		"vocational": 0.14,
		"some_college": 0.20,
		"bachelor": 0.32,
		"graduate": 0.10,
		"self_taught": 0.06,
	},
	"occupation_domain": {
		"student": 0.08,
		"service_retail": 0.14,
		"gig_flexible": 0.08,
		"office_admin": 0.13,
		"technical": 0.12,
		"creative_media": 0.08,
		"care_education": 0.11,
		"trades_manual": 0.10,
		"small_business": 0.08,
		"unemployed_between_jobs": 0.04,
		"retired": 0.04,
	},
	"economic_status": {
		"struggling": 0.10,
		"tight": 0.22,
		"stable": 0.38,
		"comfortable": 0.22,
		"affluent": 0.08,
	},
	"living_situation": {
		"with_family": 0.20,
		"shared_rental": 0.18,
		"solo_rental": 0.24,
		"partner_or_family_home": 0.22,
		"owned_home": 0.12,
		"temporary_or_unstable": 0.04,
	},
	"social_style": {
		"reserved_close_circle": 0.24,
		"warm_small_group": 0.28,
		"outgoing_connector": 0.18,
		"online_first": 0.16,
		"community_or_family_centered": 0.14,
	},
	"media_style": {
		"short_video_scroller": 0.22,
		"longform_reader": 0.16,
		"podcast_audio": 0.13,
		"gaming_streams": 0.12,
		"news_commentary": 0.13,
		"visual_lifestyle": 0.12,
		"quiet_low_media": 0.12,
	},
	"consumption_style": {
		"budget_optimizer": 0.24,
		"value_practical": 0.30,
		"experience_spender": 0.16,
		"status_aware": 0.10,
		"saver_investor": 0.12,
		"impulse_treats": 0.08,
	},
}

PRACTICAL_INTERESTS: WeightedOptions = {
	"home_cooking": 0.14,
	"casual_fitness": 0.12,
	"walking_hiking": 0.10,
	"video_games": 0.10,
	"diy_repairs": 0.08,
	"gardening_plants": 0.07,
	"music_making": 0.06,
	"photography": 0.07,
	"crafts_making": 0.07,
	"reading_writing": 0.08,
	"team_sports": 0.05,
	"volunteering": 0.04,
	"budget_travel": 0.02,
}

ASPIRATIONAL_INTERESTS: WeightedOptions = {
	"luxury_cars_watching": 0.12,
	"golf_culture_watching": 0.06,
	"high_fashion_watching": 0.08,
	"fine_dining_watching": 0.08,
	"international_travel_watching": 0.13,
	"art_collecting_watching": 0.05,
	"esports_viewing": 0.10,
	"celebrity_culture": 0.07,
	"premium_tech": 0.10,
	"home_design": 0.10,
	"motorsport": 0.05,
	"financial_freedom": 0.16,
}

HIGH_COST_CONSUMPTION_INTERESTS: WeightedOptions = {
	"luxury_car_purchase_planning": 0.04,
	"golf_membership": 0.03,
	"high_fashion_regular": 0.04,
	"fine_dining_regular": 0.04,
	"international_travel_regular": 0.04,
	"art_collecting_regular": 0.02,
}

FAMILY_WEIGHTS: dict[str, WeightedOptions] = {
	"marital_status": {
		"single": 0.34,
		"dating": 0.14,
		"married": 0.42,
		"divorced": 0.08,
		"widowed": 0.02,
	},
	"children_status": {
		"no_children": 0.48,
		"young_children": 0.16,
		"school_age_children": 0.18,
		"adult_children": 0.18,
	},
	"parent_support": {
		"no_parent_support": 0.44,
		"supports_parents_lightly": 0.38,
		"supports_parents_heavily": 0.10,
		"caregiver_for_elder": 0.08,
	},
	"family_burden": {
		"low_family_responsibility": 0.44,
		"moderate_family_responsibility": 0.42,
		"heavy_family_responsibility": 0.14,
	},
}

SPECIFIC_OPTIONS: dict[str, dict[str, list[str]]] = {
	"education": {
		"high_school": ["普通高中毕业", "职业高中毕业", "中专毕业", "成人高中同等学历"],
		"vocational": ["护理相关职校", "汽修技校", "烹饪培训学校", "电工/焊工技能培训", "美容美发职业培训", "幼教职业培训"],
		"some_college": ["大专毕业", "本科在读后退学", "成人大专在读", "专升本在读", "大学读到三年级后工作"],
		"bachelor": ["普通本科毕业", "师范类本科毕业", "计算机相关本科", "财经类本科", "艺术设计本科", "民办本科毕业"],
		"graduate": ["硕士毕业", "在职研究生毕业", "专业硕士毕业", "博士肄业后工作", "海外硕士毕业"],
		"self_taught": ["自学编程", "自学摄影剪辑", "自学电商运营", "自学手工制作", "自学外语和翻译"],
	},
	"occupation_domain": {
		"student": ["本科生", "大专生", "考研备考生", "刚毕业实习生", "职业培训学员"],
		"service_retail": ["便利店店员", "商场导购", "咖啡店店长", "餐饮服务员", "社区超市理货员", "客服专员"],
		"gig_flexible": ["外卖骑手", "网约车司机", "自由接单设计师", "兼职家教", "临时活动执行", "平台接单维修工"],
		"office_admin": ["行政助理", "人事专员", "运营专员", "财务文员", "物业办公室职员", "项目协调员"],
		"technical": ["后端开发工程师", "数据分析师", "测试工程师", "机械维修技术员", "网络运维", "产品技术支持"],
		"creative_media": ["短视频剪辑师", "平面设计师", "摄影助理", "自媒体编辑", "直播运营", "插画接单者"],
		"care_education": ["幼儿园老师", "托育中心助教", "社区社工", "养老护理员", "心理热线志愿者", "培训机构老师"],
		"trades_manual": ["水电维修工", "木工", "厨师", "仓库叉车工", "装修工", "快递站分拣员"],
		"small_business": ["小餐馆老板", "社区杂货铺店主", "网店店主", "花店经营者", "修车铺合伙人", "水果摊摊主"],
		"unemployed_between_jobs": ["刚离职的前店员", "待业技术员", "照顾家人后准备重返职场", "创业失败后休整", "合同到期的临时工"],
		"retired": ["退休工人", "退休教师", "退休护士", "返聘门卫", "半退休个体户"],
	},
	"living_situation": {
		"with_family": ["和父母同住", "和母亲同住", "三代同堂", "暂住亲戚家", "和兄弟姐妹合住"],
		"shared_rental": ["与同事合租两居室", "和陌生室友合租", "住在城中村合租房", "与朋友合租老小区", "租住群租隔间"],
		"solo_rental": ["独自租一居室", "租住开间公寓", "租住老小区单间", "租住公司附近小公寓", "住在带阳台的小单间"],
		"partner_or_family_home": ["和伴侣租房", "和配偶孩子同住", "夫妻住在老小区", "和伴侣及宠物同住", "小家庭住在郊区"],
		"owned_home": ["住在自有老房", "住在贷款中的两居室", "住在父母留下的房子", "住在自购小公寓", "住在郊区自住房"],
		"temporary_or_unstable": ["短租过渡房", "单位宿舍床位", "借住朋友家", "频繁搬家的合租房", "工地附近临时住处"],
	},
	"media_style": {
		"short_video_scroller": ["每天刷短视频", "常看直播切片", "睡前刷本地生活视频", "通勤时刷短视频"],
		"longform_reader": ["常看长文和深度帖子", "习惯读书评和长帖", "订阅几个长内容作者", "喜欢慢慢看知识类文章"],
		"podcast_audio": ["通勤听播客", "做家务时听访谈", "睡前听音频节目", "常听社会议题播客"],
		"gaming_streams": ["常看游戏直播", "追电竞赛事解说", "看游戏攻略视频", "关注主机游戏评测"],
		"news_commentary": ["关注热点新闻评论", "常看时事解读", "喜欢围观公共议题讨论", "订阅财经和社会新闻"],
		"visual_lifestyle": ["爱看穿搭家居图文", "收藏生活方式笔记", "刷美食旅行内容", "喜欢看审美化日常分享"],
		"quiet_low_media": ["很少主动刷平台", "只偶尔看朋友转发", "每天只看一小会儿消息", "更偏线下生活"],
	},
	"consumption_style": {
		"budget_optimizer": ["买东西先比价", "偏爱打折和二手", "记账后再消费", "能省则省"],
		"value_practical": ["重视耐用和实用", "愿意为好用付合理价格", "不追潮流但讲究质量", "喜欢性价比高的选择"],
		"experience_spender": ["愿意为旅行和课程花钱", "会为一次好体验破预算", "偏爱餐厅和活动体验", "把钱花在见识上"],
		"status_aware": ["在意体面和品牌形象", "偶尔为撑场面买贵东西", "重视外表和社交观感", "喜欢能被看见的品质"],
		"saver_investor": ["固定储蓄", "关注基金和理财", "会为长期目标克制消费", "喜欢规划未来现金流"],
		"impulse_treats": ["偶尔冲动下单", "压力大时买小东西犒赏自己", "容易被直播种草", "喜欢小额即时满足"],
	},
}

SPECIFIC_VALUE_WEIGHTS: dict[str, dict[str, WeightedOptions]] = {
	"education": {
		"high_school": {"普通高中毕业": 0.42, "职业高中毕业": 0.18, "中专毕业": 0.26, "成人高中同等学历": 0.14},
		"vocational": {"护理相关职校": 0.16, "汽修技校": 0.14, "烹饪培训学校": 0.16, "电工/焊工技能培训": 0.18, "美容美发职业培训": 0.18, "幼教职业培训": 0.18},
		"some_college": {"大专毕业": 0.38, "本科在读后退学": 0.12, "成人大专在读": 0.18, "专升本在读": 0.18, "大学读到三年级后工作": 0.14},
		"bachelor": {"普通本科毕业": 0.38, "师范类本科毕业": 0.14, "计算机相关本科": 0.16, "财经类本科": 0.14, "艺术设计本科": 0.08, "民办本科毕业": 0.10},
		"graduate": {"硕士毕业": 0.42, "在职研究生毕业": 0.22, "专业硕士毕业": 0.22, "博士肄业后工作": 0.04, "海外硕士毕业": 0.10},
		"self_taught": {"自学编程": 0.22, "自学摄影剪辑": 0.20, "自学电商运营": 0.22, "自学手工制作": 0.18, "自学外语和翻译": 0.18},
	},
	"living_situation": {
		"with_family": {"和父母同住": 0.30, "和母亲同住": 0.18, "三代同堂": 0.24, "暂住亲戚家": 0.12, "和兄弟姐妹合住": 0.16},
		"shared_rental": {"与同事合租两居室": 0.22, "和陌生室友合租": 0.22, "住在城中村合租房": 0.20, "与朋友合租老小区": 0.24, "租住群租隔间": 0.12},
		"solo_rental": {"独自租一居室": 0.26, "租住开间公寓": 0.24, "租住老小区单间": 0.18, "租住公司附近小公寓": 0.22, "住在带阳台的小单间": 0.10},
		"partner_or_family_home": {"和伴侣租房": 0.20, "和配偶孩子同住": 0.32, "夫妻住在老小区": 0.20, "和伴侣及宠物同住": 0.12, "小家庭住在郊区": 0.16},
		"owned_home": {"住在自有老房": 0.24, "住在贷款中的两居室": 0.24, "住在父母留下的房子": 0.16, "住在自购小公寓": 0.18, "住在郊区自住房": 0.18},
		"temporary_or_unstable": {"短租过渡房": 0.28, "单位宿舍床位": 0.20, "借住朋友家": 0.20, "频繁搬家的合租房": 0.18, "工地附近临时住处": 0.14},
	},
	"media_style": {
		"short_video_scroller": {"每天刷短视频": 0.32, "常看直播切片": 0.18, "睡前刷本地生活视频": 0.24, "通勤时刷短视频": 0.26},
		"longform_reader": {"常看长文和深度帖子": 0.28, "习惯读书评和长帖": 0.22, "订阅几个长内容作者": 0.24, "喜欢慢慢看知识类文章": 0.26},
		"podcast_audio": {"通勤听播客": 0.34, "做家务时听访谈": 0.20, "睡前听音频节目": 0.22, "常听社会议题播客": 0.24},
		"gaming_streams": {"常看游戏直播": 0.30, "追电竞赛事解说": 0.26, "看游戏攻略视频": 0.26, "关注主机游戏评测": 0.18},
		"news_commentary": {"关注热点新闻评论": 0.34, "常看时事解读": 0.28, "喜欢围观公共议题讨论": 0.22, "订阅财经和社会新闻": 0.16},
		"visual_lifestyle": {"爱看穿搭家居图文": 0.26, "收藏生活方式笔记": 0.30, "刷美食旅行内容": 0.24, "喜欢看审美化日常分享": 0.20},
		"quiet_low_media": {"很少主动刷平台": 0.26, "只偶尔看朋友转发": 0.30, "每天只看一小会儿消息": 0.28, "更偏线下生活": 0.16},
	},
	"consumption_style": {
		"budget_optimizer": {"买东西先比价": 0.34, "偏爱打折和二手": 0.26, "记账后再消费": 0.20, "能省则省": 0.20},
		"value_practical": {"重视耐用和实用": 0.32, "愿意为好用付合理价格": 0.22, "不追潮流但讲究质量": 0.22, "喜欢性价比高的选择": 0.24},
		"experience_spender": {"愿意为旅行和课程花钱": 0.24, "会为一次好体验破预算": 0.18, "偏爱餐厅和活动体验": 0.32, "把钱花在见识上": 0.26},
		"status_aware": {"在意体面和品牌形象": 0.28, "偶尔为撑场面买贵东西": 0.18, "重视外表和社交观感": 0.30, "喜欢能被看见的品质": 0.24},
		"saver_investor": {"固定储蓄": 0.30, "关注基金和理财": 0.22, "会为长期目标克制消费": 0.28, "喜欢规划未来现金流": 0.20},
		"impulse_treats": {"偶尔冲动下单": 0.30, "压力大时买小东西犒赏自己": 0.28, "容易被直播种草": 0.28, "喜欢小额即时满足": 0.14},
	},
}

SPECIFIC_INTERESTS: dict[str, list[str]] = {
	"home_cooking": ["研究家常菜", "做低成本便当", "烘焙小点心", "复刻短视频食谱", "给家人做汤"],
	"casual_fitness": ["夜跑", "居家跟练", "跳操", "骑共享单车", "下班后去健身房"],
	"walking_hiking": ["城市散步", "近郊徒步", "公园快走", "周末爬山", "沿河步道散心"],
	"video_games": ["手机游戏", "主机游戏", "多人竞技游戏", "模拟经营游戏", "独立游戏"],
	"diy_repairs": ["修小家电", "改造旧家具", "组装电脑", "修自行车", "做收纳架"],
	"gardening_plants": ["养多肉", "阳台种菜", "照顾绿萝和龟背竹", "研究花盆土", "养香草植物"],
	"music_making": ["弹吉他", "唱歌录音", "写简单旋律", "玩电子琴", "剪辑翻唱视频"],
	"photography": ["手机街拍", "拍宠物和家人", "拍探店照片", "修图调色", "拍城市夜景"],
	"crafts_making": ["做手账", "拼模型", "做黏土小物", "缝布艺", "做木质小摆件"],
	"reading_writing": ["写日记", "读小说", "写影评", "看非虚构书", "写长帖"],
	"team_sports": ["打羽毛球", "打篮球", "踢五人制足球", "打乒乓球", "参加社区球局"],
	"volunteering": ["社区志愿活动", "流浪动物救助", "公益市集帮忙", "给老人送物资", "参与环保活动"],
	"budget_travel": ["周边一日游", "坐绿皮火车旅行", "低价机票攻略", "青旅旅行", "城市徒步打卡"],
	"luxury_cars_watching": ["看豪车测评", "收藏跑车图片", "看改装车视频", "关注车展", "听引擎声合集"],
	"golf_culture_watching": ["看高尔夫赛事", "关注高尔夫穿搭", "刷球场生活方式内容", "看球杆测评", "向往会员制球场"],
	"high_fashion_watching": ["看秀场视频", "关注潮牌联名", "收藏穿搭图", "看高定工艺纪录片", "研究设计师品牌"],
	"fine_dining_watching": ["看高级餐厅探店", "收藏米其林榜单", "关注侍酒和菜单设计", "看主厨纪录片", "向往预约制餐厅"],
	"international_travel_watching": ["看海外旅行 vlog", "收藏城市攻略", "关注移居生活分享", "看廉航攻略", "向往长线旅行"],
	"art_collecting_watching": ["看画廊展览内容", "收藏艺术家访谈", "关注版画和小雕塑", "看拍卖新闻", "逛艺术市集"],
	"esports_viewing": ["追电竞比赛", "看战术复盘", "关注职业选手", "看赛事直播", "刷精彩操作剪辑"],
	"celebrity_culture": ["追综艺片段", "看明星访谈", "围观娱乐新闻", "关注演员动态", "收藏舞台剪辑"],
	"premium_tech": ["看旗舰手机测评", "关注电脑硬件", "收藏耳机评测", "看智能家居视频", "研究新款平板"],
	"home_design": ["看家装案例", "收藏户型改造", "关注收纳设计", "看理想住宅视频", "研究软装搭配"],
	"motorsport": ["看 F1 集锦", "关注拉力赛", "看赛车纪录片", "研究赛道和车队", "看摩托车赛事"],
	"financial_freedom": ["看财富自由故事", "关注副业经验", "收藏理财方法", "看创业复盘", "研究提前退休案例"],
	"luxury_car_purchase_planning": ["认真比较豪华品牌车型", "关注豪车贷款和保养成本", "计划几年内置换高端车", "研究豪华新能源车配置"],
	"golf_membership": ["固定去高尔夫练习场", "考虑球会会员权益", "关注球具升级和课程", "安排商务高尔夫活动"],
	"high_fashion_regular": ["定期购买设计师品牌", "关注高端买手店上新", "为重要场合配置高级成衣", "维护几件高价经典款"],
	"fine_dining_regular": ["定期预约高级餐厅", "关注酒单和主厨菜单", "把高级餐饮当作社交安排", "为纪念日预订精致餐厅"],
	"international_travel_regular": ["每年安排海外旅行", "关注长线航班和高端酒店", "规划跨国度假路线", "熟悉签证和境外交通"],
	"art_collecting_regular": ["定期购买版画或小型雕塑", "关注画廊和拍卖预展", "和艺术顾问保持联系", "为家里添置艺术品"],
}

SPECIFIC_OCCUPATION_WEIGHTS: dict[str, WeightedOptions] = {
	"student": {"本科生": 0.35, "大专生": 0.24, "考研备考生": 0.16, "刚毕业实习生": 0.18, "职业培训学员": 0.07},
	"service_retail": {"便利店店员": 0.18, "商场导购": 0.16, "咖啡店店长": 0.11, "餐饮服务员": 0.22, "社区超市理货员": 0.18, "客服专员": 0.15},
	"gig_flexible": {"外卖骑手": 0.22, "网约车司机": 0.16, "自由接单设计师": 0.12, "兼职家教": 0.12, "临时活动执行": 0.18, "平台接单维修工": 0.20},
	"office_admin": {"行政助理": 0.19, "人事专员": 0.16, "运营专员": 0.22, "财务文员": 0.14, "物业办公室职员": 0.14, "项目协调员": 0.15},
	"technical": {"后端开发工程师": 0.20, "数据分析师": 0.18, "测试工程师": 0.18, "机械维修技术员": 0.17, "网络运维": 0.17, "产品技术支持": 0.10},
	"creative_media": {"短视频剪辑师": 0.22, "平面设计师": 0.16, "摄影助理": 0.13, "自媒体编辑": 0.18, "直播运营": 0.20, "插画接单者": 0.11},
	"care_education": {"幼儿园老师": 0.18, "托育中心助教": 0.18, "社区社工": 0.16, "养老护理员": 0.18, "心理热线志愿者": 0.08, "培训机构老师": 0.22},
	"trades_manual": {"水电维修工": 0.20, "木工": 0.12, "厨师": 0.18, "仓库叉车工": 0.15, "装修工": 0.17, "快递站分拣员": 0.18},
	"small_business": {"小餐馆老板": 0.20, "社区杂货铺店主": 0.18, "网店店主": 0.20, "花店经营者": 0.13, "修车铺合伙人": 0.12, "水果摊摊主": 0.17},
	"unemployed_between_jobs": {"刚离职的前店员": 0.22, "待业技术员": 0.14, "照顾家人后准备重返职场": 0.20, "创业失败后休整": 0.14, "合同到期的临时工": 0.30},
	"retired": {"退休工人": 0.28, "退休教师": 0.18, "退休护士": 0.12, "返聘门卫": 0.16, "半退休个体户": 0.26},
}

SPECIFIC_OCCUPATION_RULES: tuple[InfluenceRule, ...] = (
	InfluenceRule("education", ("bachelor", "graduate"), "specific_occupation", {"便利店店员": 0.45, "餐饮服务员": 0.55, "社区超市理货员": 0.5, "客服专员": 1.15, "咖啡店店长": 1.4, "商场导购": 0.8}, "高学历在服务零售中更可能进入管理、客服或更稳定岗位，基础服务岗位仍保留低概率。"),
	InfluenceRule("education", ("high_school", "vocational"), "specific_occupation", {"便利店店员": 1.25, "餐饮服务员": 1.25, "社区超市理货员": 1.2, "咖啡店店长": 0.75, "客服专员": 0.85}, "较短教育路径在服务零售中更常见一线岗位。"),
	InfluenceRule("education", ("bachelor", "graduate"), "specific_occupation", {"后端开发工程师": 1.45, "数据分析师": 1.45, "测试工程师": 1.25, "产品技术支持": 1.15, "机械维修技术员": 0.75, "网络运维": 1.05}, "本科及以上更常进入软件、数据和测试等技术岗位。"),
	InfluenceRule("education", ("vocational", "self_taught"), "specific_occupation", {"机械维修技术员": 1.45, "网络运维": 1.25, "产品技术支持": 1.1, "后端开发工程师": 0.75, "数据分析师": 0.75}, "职教和自学路径更常见维修、运维和支持类技术岗位。"),
	InfluenceRule("education", ("bachelor", "graduate"), "specific_occupation", {"行政助理": 0.75, "人事专员": 1.25, "运营专员": 1.35, "财务文员": 1.2, "项目协调员": 1.3, "物业办公室职员": 0.65}, "高学历办公室岗位更偏运营、人事、财务和项目协调。"),
	InfluenceRule("education", ("high_school", "vocational"), "specific_occupation", {"物业办公室职员": 1.25, "行政助理": 1.15, "运营专员": 0.8, "项目协调员": 0.75}, "较短教育路径在办公室类岗位里更偏基础行政和物业办公室。"),
	InfluenceRule("education", ("bachelor", "graduate"), "specific_occupation", {"幼儿园老师": 1.25, "社区社工": 1.35, "心理热线志愿者": 1.25, "培训机构老师": 1.35, "养老护理员": 0.65}, "高学历助人行业更偏教育、社工和培训。"),
	InfluenceRule("education", ("high_school", "vocational"), "specific_occupation", {"托育中心助教": 1.2, "养老护理员": 1.35, "心理热线志愿者": 0.45, "培训机构老师": 0.75}, "较短教育路径在助人行业里更常见照护和助教岗位。"),
	InfluenceRule("education", ("bachelor", "graduate"), "specific_occupation", {"自媒体编辑": 1.35, "平面设计师": 1.2, "直播运营": 1.2, "摄影助理": 0.75, "插画接单者": 1.1}, "高学历创意媒体岗位更偏编辑、设计和运营。"),
	InfluenceRule("education", ("self_taught", "vocational"), "specific_occupation", {"短视频剪辑师": 1.35, "摄影助理": 1.2, "插画接单者": 1.25, "自媒体编辑": 0.85}, "自学和职教路径更常见实操型创意岗位。"),
	InfluenceRule("age_band", ("18-24",), "specific_occupation", {"刚毕业实习生": 1.8, "本科生": 1.35, "大专生": 1.3, "职业培训学员": 1.2, "考研备考生": 1.15}, "18-24 的学生类身份更偏在读、实习和培训。"),
	InfluenceRule("age_band", ("25-34",), "specific_occupation", {"刚毕业实习生": 0.55, "考研备考生": 0.85, "职业培训学员": 1.1}, "25-34 仍可能深造或转行，但刚毕业实习下降。"),
	InfluenceRule("age_band", ("45-54", "55+"), "specific_occupation", {"退休工人": 1.35, "退休教师": 1.2, "半退休个体户": 1.35, "退休护士": 1.1}, "45+ 退休/半退休具体身份更偏长期职业延续。"),
	InfluenceRule("economic_status", ("comfortable", "affluent"), "specific_occupation", {"咖啡店店长": 1.45, "客服专员": 1.15, "便利店店员": 0.5, "餐饮服务员": 0.55, "社区超市理货员": 0.55}, "经济较好时，服务零售一线岗位概率降低，店长或稳定岗位概率提高。"),
	InfluenceRule("economic_status", ("struggling", "tight"), "specific_occupation", {"便利店店员": 1.25, "餐饮服务员": 1.25, "社区超市理货员": 1.2, "咖啡店店长": 0.7}, "经济压力较大时，一线服务岗位更常见。"),
	InfluenceRule("economic_status", ("comfortable", "affluent"), "specific_occupation", {"小餐馆老板": 1.2, "网店店主": 1.2, "花店经营者": 1.2, "水果摊摊主": 0.75}, "经济较好时，小生意更可能是较稳定或品牌化经营。"),
	InfluenceRule("economic_status", ("struggling", "tight"), "specific_occupation", {"水果摊摊主": 1.3, "修车铺合伙人": 1.15, "小餐馆老板": 0.9, "花店经营者": 0.8}, "经济较紧时，小生意更偏现金流压力较大的小摊小铺。"),
)

SPECIFIC_VALUE_RULES: tuple[InfluenceRule, ...] = (
	InfluenceRule("age_band", ("18-24",), "specific_education", {"本科在读后退学": 1.4, "专升本在读": 1.35, "成人大专在读": 0.75, "大学读到三年级后工作": 0.85}, "18-24 的非完整本科/大专经历更偏仍在读或刚离校。"),
	InfluenceRule("age_band", ("45-54", "55+"), "specific_education", {"成人高中同等学历": 1.35, "中专毕业": 1.25, "职业高中毕业": 1.15, "普通高中毕业": 0.9}, "中老年样本的高中同等路径和中专路径略高。"),
	InfluenceRule("occupation_domain", ("technical",), "specific_education", {"计算机相关本科": 1.7, "财经类本科": 0.75, "艺术设计本科": 0.65}, "技术岗位更常见计算机相关本科背景。"),
	InfluenceRule("occupation_domain", ("care_education",), "specific_education", {"师范类本科毕业": 1.6, "护理相关职校": 1.55, "幼教职业培训": 1.45}, "教育照护类职业更常连接师范、护理和幼教路径。"),
	InfluenceRule("occupation_domain", ("creative_media",), "specific_education", {"艺术设计本科": 1.65, "自学摄影剪辑": 1.55, "自学手工制作": 1.25}, "创意媒体类职业更常连接设计、剪辑和手作自学路径。"),
	InfluenceRule("age_band", ("18-24",), "specific_living_situation", {"和父母同住": 1.45, "和陌生室友合租": 1.3, "租住群租隔间": 1.25, "和配偶孩子同住": 0.35, "住在贷款中的两居室": 0.35}, "18-24 的具体居住细节更偏原生家庭、合租或低成本租住。"),
	InfluenceRule("age_band", ("35-44", "45-54"), "specific_living_situation", {"和配偶孩子同住": 1.45, "夫妻住在老小区": 1.25, "小家庭住在郊区": 1.25, "住在贷款中的两居室": 1.35}, "中年阶段的具体住所更偏伴侣、孩子和贷款住房。"),
	InfluenceRule("age_band", ("55+",), "specific_living_situation", {"三代同堂": 1.55, "住在自有老房": 1.65, "住在父母留下的房子": 1.45, "与朋友合租老小区": 1.25, "租住群租隔间": 0.35, "住在带阳台的小单间": 0.55}, "55+ 的具体住所更偏长期老房、家庭同住或熟人式合住。"),
	InfluenceRule("economic_status", ("struggling", "tight"), "specific_living_situation", {"租住群租隔间": 1.45, "住在城中村合租房": 1.35, "短租过渡房": 1.35, "借住朋友家": 1.3, "住在自有老房": 1.25, "住在贷款中的两居室": 0.65, "住在自购小公寓": 0.55}, "经济较紧时，低成本租住、借住和老房更常见。"),
	InfluenceRule("economic_status", ("comfortable", "affluent"), "specific_living_situation", {"住在自购小公寓": 1.35, "住在郊区自住房": 1.35, "住在贷款中的两居室": 1.2, "租住群租隔间": 0.35, "工地附近临时住处": 0.35}, "经济较宽裕时，具体住所更稳定、独立或自有。"),
	InfluenceRule("platform_archetype", ("short_video_mass",), "specific_media_habit", {"每天刷短视频": 1.45, "睡前刷本地生活视频": 1.35, "常看直播切片": 1.25}, "短视频平台原型强化高频短视频习惯。"),
	InfluenceRule("platform_archetype", ("public_discussion",), "specific_media_habit", {"关注热点新闻评论": 1.45, "常看时事解读": 1.35, "喜欢围观公共议题讨论": 1.25}, "公共讨论平台原型强化热点和议题内容。"),
	InfluenceRule("platform_archetype", ("lifestyle_discovery",), "specific_media_habit", {"收藏生活方式笔记": 1.45, "刷美食旅行内容": 1.35, "爱看穿搭家居图文": 1.25}, "生活方式平台原型强化图文收藏、种草和审美内容。"),
	InfluenceRule("platform_archetype", ("interest_community",), "specific_media_habit", {"订阅几个长内容作者": 1.35, "看游戏攻略视频": 1.35, "关注主机游戏评测": 1.25, "常看长文和深度帖子": 1.25}, "兴趣社区原型强化长内容、攻略和垂直评测。"),
	InfluenceRule("age_band", ("55+",), "specific_media_habit", {"只偶尔看朋友转发": 1.45, "每天只看一小会儿消息": 1.35, "更偏线下生活": 1.25, "追电竞赛事解说": 0.45}, "55+ 的具体媒体习惯更偏低强度和熟人转发。"),
	InfluenceRule("economic_status", ("struggling", "tight"), "specific_consumption_habit", {"买东西先比价": 1.45, "偏爱打折和二手": 1.35, "记账后再消费": 1.25, "偶尔为撑场面买贵东西": 0.55}, "经济较紧时，具体消费习惯更偏比价、折扣和预算控制。"),
	InfluenceRule("economic_status", ("comfortable", "affluent"), "specific_consumption_habit", {"愿意为好用付合理价格": 1.35, "偏爱餐厅和活动体验": 1.35, "把钱花在见识上": 1.25, "能省则省": 0.55}, "经济较宽裕时，具体消费更容易转向品质和体验。"),
	InfluenceRule("platform_archetype", ("lifestyle_discovery",), "specific_consumption_habit", {"容易被直播种草": 1.35, "重视外表和社交观感": 1.25, "偏爱餐厅和活动体验": 1.25}, "生活方式平台会提高种草、外观和体验消费细节。"),
)

INTEREST_LABELS: dict[str, str] = {
	"home_cooking": "日常做饭/研究食谱",
	"casual_fitness": "低门槛健身",
	"walking_hiking": "散步、徒步和近郊活动",
	"video_games": "电子游戏",
	"diy_repairs": "动手维修和改造",
	"gardening_plants": "植物和园艺",
	"music_making": "唱歌、乐器或编曲",
	"photography": "摄影和修图",
	"crafts_making": "手作、拼装或工艺",
	"reading_writing": "阅读和写作",
	"team_sports": "参与型球类/团队运动",
	"volunteering": "社区志愿活动",
	"budget_travel": "低预算旅行",
	"luxury_cars_watching": "豪车文化观看/向往",
	"golf_culture_watching": "高尔夫赛事/高尔夫生活方式观看",
	"high_fashion_watching": "高定、潮牌或时尚产业观看",
	"fine_dining_watching": "高级餐厅和美食评鉴观看",
	"international_travel_watching": "海外旅行和异国生活方式观看",
	"art_collecting_watching": "艺术收藏和画廊文化观看",
	"esports_viewing": "电竞赛事观看",
	"celebrity_culture": "明星、娱乐圈和粉丝文化",
	"premium_tech": "高端电子产品",
	"home_design": "理想住宅和室内设计",
	"motorsport": "赛车和改装文化",
	"financial_freedom": "财富自由叙事",
	"luxury_car_purchase_planning": "豪华车购买计划",
	"golf_membership": "高尔夫会员/固定练习",
	"high_fashion_regular": "高端时尚持续消费",
	"fine_dining_regular": "高级餐厅持续消费",
	"international_travel_regular": "定期海外旅行",
	"art_collecting_regular": "艺术品持续收藏",
}

CATEGORY_LABELS: dict[str, dict[str, str]] = {
	"platform_archetype": {
		"private_social": "熟人社交和朋友圈式内容",
		"short_video_mass": "大众短视频平台",
		"public_discussion": "公共讨论和热点信息流",
		"lifestyle_discovery": "生活方式发现和消费种草",
		"interest_community": "兴趣社区和长内容平台",
	},
	"age_band": {"18-24": "18-24 岁", "25-34": "25-34 岁", "35-44": "35-44 岁", "45-54": "45-54 岁", "55+": "55 岁及以上"},
	"education": {
		"high_school": "高中或同等学历",
		"vocational": "职业教育/技能培训",
		"some_college": "大专、大学在读或未完成本科",
		"bachelor": "本科",
		"graduate": "研究生及以上",
		"self_taught": "主要靠自学形成技能",
	},
	"occupation_domain": {
		"student": "学生或刚进入社会",
		"service_retail": "服务业/零售",
		"gig_flexible": "灵活就业/零工",
		"office_admin": "办公室行政/运营",
		"technical": "技术/工程/数据相关",
		"creative_media": "创意、内容或媒体",
		"care_education": "照护、教育或助人行业",
		"trades_manual": "技工、维修或体力技能行业",
		"small_business": "个体户/小生意",
		"unemployed_between_jobs": "待业或换工作间隙",
		"retired": "退休或半退休",
	},
	"economic_status": {"struggling": "明显拮据", "tight": "手头偏紧", "stable": "基本稳定", "comfortable": "比较宽裕", "affluent": "富裕"},
	"living_situation": {
		"with_family": "与父母或亲属同住",
		"shared_rental": "合租",
		"solo_rental": "独自租住",
		"partner_or_family_home": "与伴侣/小家庭同住",
		"owned_home": "自有住房",
		"temporary_or_unstable": "临时或不稳定住所",
	},
	"social_style": {
		"reserved_close_circle": "内敛，重视熟人小圈子",
		"warm_small_group": "温和，偏小团体互动",
		"outgoing_connector": "外向，喜欢连接不同人群",
		"online_first": "线上优先，网络关系重要",
		"community_or_family_centered": "家庭/社区中心型",
	},
	"media_style": {
		"short_video_scroller": "短视频和碎片内容",
		"longform_reader": "长文、书籍或深度内容",
		"podcast_audio": "播客/音频内容",
		"gaming_streams": "游戏直播和视频",
		"news_commentary": "新闻评论和时事",
		"visual_lifestyle": "视觉生活方式内容",
		"quiet_low_media": "低媒体摄入",
	},
	"consumption_style": {
		"budget_optimizer": "精打细算型",
		"value_practical": "重视实用和性价比",
		"experience_spender": "愿意为体验花钱",
		"status_aware": "在意身份感和体面",
		"saver_investor": "储蓄/投资导向",
		"impulse_treats": "偶尔冲动犒赏自己",
	},
}

PLATFORM_INFLUENCE_RULES: tuple[InfluenceRule, ...] = (
	InfluenceRule("platform_archetype", ("private_social",), "age_band", {"35-44": 1.2, "45-54": 1.25, "55+": 1.3, "18-24": 0.75}, "熟人社交覆盖全年龄层，中年和 55+ 权重更高。"),
	InfluenceRule("platform_archetype", ("short_video_mass",), "age_band", {"25-34": 1.15, "35-44": 1.15, "45-54": 1.1, "55+": 1.05, "18-24": 0.95}, "大众短视频平台覆盖广，年龄分布更接近全域用户。"),
	InfluenceRule("platform_archetype", ("public_discussion",), "age_band", {"25-34": 1.2, "35-44": 1.15, "18-24": 0.95, "55+": 0.75}, "公共讨论平台更集中在青年和中年活跃表达用户。"),
	InfluenceRule("platform_archetype", ("lifestyle_discovery",), "age_band", {"18-24": 1.35, "25-34": 1.45, "35-44": 0.95, "45-54": 0.65, "55+": 0.45}, "生活方式和消费发现平台更偏年轻及年轻中年用户。"),
	InfluenceRule("platform_archetype", ("interest_community",), "age_band", {"18-24": 1.45, "25-34": 1.25, "35-44": 0.9, "45-54": 0.65, "55+": 0.45}, "兴趣社区和长内容平台更偏年轻用户。"),
	InfluenceRule("platform_archetype", ("private_social",), "social_style", {"community_or_family_centered": 1.8, "warm_small_group": 1.35, "online_first": 0.75, "outgoing_connector": 0.85}, "熟人社交更围绕家庭、同事、邻里和小圈子。"),
	InfluenceRule("platform_archetype", ("short_video_mass",), "social_style", {"online_first": 1.25, "reserved_close_circle": 1.1, "outgoing_connector": 1.05}, "短视频平台既有观看型用户，也有轻互动的线上娱乐用户。"),
	InfluenceRule("platform_archetype", ("public_discussion",), "social_style", {"outgoing_connector": 1.35, "online_first": 1.25, "reserved_close_circle": 0.8}, "公共讨论平台提高表达、转发和连接陌生议题圈层的概率。"),
	InfluenceRule("platform_archetype", ("lifestyle_discovery",), "social_style", {"warm_small_group": 1.25, "online_first": 1.2, "community_or_family_centered": 0.75}, "生活方式发现平台更常见轻分享、小圈层种草和评论互动。"),
	InfluenceRule("platform_archetype", ("interest_community",), "social_style", {"online_first": 1.55, "reserved_close_circle": 1.2, "community_or_family_centered": 0.55}, "兴趣社区更容易形成线上同好关系。"),
	InfluenceRule("platform_archetype", ("private_social",), "media_style", {"quiet_low_media": 1.35, "news_commentary": 1.15, "visual_lifestyle": 0.8, "gaming_streams": 0.55}, "熟人社交用户的内容摄入更生活化，不一定高强度刷内容。"),
	InfluenceRule("platform_archetype", ("short_video_mass",), "media_style", {"short_video_scroller": 2.1, "visual_lifestyle": 1.15, "longform_reader": 0.55, "podcast_audio": 0.65}, "短视频平台显著提高碎片内容消费概率。"),
	InfluenceRule("platform_archetype", ("public_discussion",), "media_style", {"news_commentary": 2.0, "longform_reader": 1.15, "short_video_scroller": 0.9, "quiet_low_media": 0.55}, "公共讨论平台提高热点、新闻评论和长帖阅读概率。"),
	InfluenceRule("platform_archetype", ("lifestyle_discovery",), "media_style", {"visual_lifestyle": 2.0, "short_video_scroller": 1.25, "news_commentary": 0.55, "gaming_streams": 0.55}, "生活方式发现平台更偏图文、审美和消费内容。"),
	InfluenceRule("platform_archetype", ("interest_community",), "media_style", {"gaming_streams": 1.75, "longform_reader": 1.45, "podcast_audio": 1.15, "visual_lifestyle": 0.75}, "兴趣社区更偏长内容、视频解析、游戏和垂直知识。"),
	InfluenceRule("platform_archetype", ("private_social",), "consumption_style", {"value_practical": 1.35, "budget_optimizer": 1.15, "experience_spender": 0.85}, "熟人社交内容更贴近日常实用和家庭消费。"),
	InfluenceRule("platform_archetype", ("short_video_mass",), "consumption_style", {"impulse_treats": 1.35, "value_practical": 1.15, "budget_optimizer": 1.05}, "短视频平台提高冲动小额消费和实用推荐的影响。"),
	InfluenceRule("platform_archetype", ("public_discussion",), "consumption_style", {"saver_investor": 1.25, "value_practical": 1.15, "impulse_treats": 0.75}, "公共讨论平台更常暴露经济、职场和理性消费议题。"),
	InfluenceRule("platform_archetype", ("lifestyle_discovery",), "consumption_style", {"experience_spender": 1.55, "status_aware": 1.35, "impulse_treats": 1.2, "budget_optimizer": 0.7}, "生活方式发现平台提高体验消费、审美消费和种草概率。"),
	InfluenceRule("platform_archetype", ("interest_community",), "consumption_style", {"value_practical": 1.25, "saver_investor": 1.1, "status_aware": 0.75}, "兴趣社区更容易围绕装备、教程和理性比较形成消费。"),
)

INFLUENCE_RULES: tuple[InfluenceRule, ...] = (
	InfluenceRule("age_band", ("18-24",), "education", {"some_college": 1.8, "bachelor": 1.4, "graduate": 0.45}, "年轻成年人更可能正在接受或刚完成高等教育。"),
	InfluenceRule("age_band", ("55+",), "education", {"high_school": 1.4, "vocational": 1.25, "graduate": 0.8}, "55+ 人群的教育分布更偏向较早完成的教育路径。"),
	InfluenceRule("age_band", ("18-24",), "occupation_domain", {"student": 3.6, "gig_flexible": 1.5, "service_retail": 1.35, "retired": 0.01, "small_business": 0.5}, "18-24 更可能在读、兼职或处于早期职业阶段。"),
	InfluenceRule("age_band", ("25-34",), "occupation_domain", {"student": 0.45, "office_admin": 1.15, "technical": 1.15, "creative_media": 1.15, "care_education": 1.1, "retired": 0.01}, "25-34 通常已进入较稳定的工作阶段，学生身份下降但仍可能深造。"),
	InfluenceRule("age_band", ("35-44",), "occupation_domain", {"student": 0.08, "office_admin": 1.2, "technical": 1.2, "care_education": 1.15, "trades_manual": 1.15, "small_business": 1.2, "retired": 0.02}, "35-44 更常处于稳定职业、技能行业或经营阶段，学生身份是低概率例外。"),
	InfluenceRule("age_band", ("45-54",), "occupation_domain", {"student": 0.03, "office_admin": 1.15, "technical": 1.05, "care_education": 1.15, "trades_manual": 1.2, "small_business": 1.25, "retired": 0.15}, "45-54 更偏成熟职业、个体经营或技能行业，少数人可能提前退休或再学习。"),
	InfluenceRule("age_band", ("55+",), "occupation_domain", {"retired": 14.0, "small_business": 1.35, "student": 0.02, "gig_flexible": 0.4}, "55+ 明显提高退休或半退休概率，同时保留继续经营和工作的可能。"),
	InfluenceRule("age_band", ("18-24",), "economic_status", {"struggling": 1.8, "tight": 1.6, "comfortable": 0.55, "affluent": 0.25}, "20 岁左右通常积累较少，经济状态更偏紧。"),
	InfluenceRule("age_band", ("35-44", "45-54"), "economic_status", {"stable": 1.2, "comfortable": 1.25, "struggling": 0.75}, "中年阶段更可能有稳定收入和积累。"),
	InfluenceRule("age_band", ("55+",), "economic_status", {"stable": 1.15, "comfortable": 1.1, "affluent": 0.95, "tight": 1.1}, "55+ 经济状态分化：可能稳定，也可能受退休收入约束。"),
	InfluenceRule("education", ("graduate",), "economic_status", {"comfortable": 1.45, "affluent": 1.3, "struggling": 0.55}, "更高学历通常提高高收入职业入口概率。"),
	InfluenceRule("education", ("high_school", "vocational"), "economic_status", {"struggling": 1.25, "tight": 1.25, "affluent": 0.65}, "较短教育路径总体降低高收入职业概率，但不排除例外。"),
	InfluenceRule("occupation_domain", ("technical",), "economic_status", {"stable": 1.3, "comfortable": 1.45, "affluent": 1.25, "struggling": 0.45}, "技术岗位平均收入更容易稳定。"),
	InfluenceRule("occupation_domain", ("service_retail", "gig_flexible"), "economic_status", {"struggling": 1.45, "tight": 1.35, "comfortable": 0.65, "affluent": 0.35}, "服务业和灵活零工收入更容易波动。"),
	InfluenceRule("occupation_domain", ("small_business",), "economic_status", {"struggling": 1.15, "comfortable": 1.25, "affluent": 1.2}, "小生意收入分化较强，既可能紧张也可能较好。"),
	InfluenceRule("occupation_domain", ("retired",), "economic_status", {"tight": 1.35, "stable": 1.2, "affluent": 0.75}, "退休后的现金流更依赖养老金和积蓄。"),
	InfluenceRule("age_band", ("18-24",), "living_situation", {"with_family": 1.8, "shared_rental": 1.8, "owned_home": 0.08, "partner_or_family_home": 0.45}, "年轻人更常与家人同住、合租或住校。"),
	InfluenceRule("age_band", ("35-44", "45-54"), "living_situation", {"partner_or_family_home": 1.6, "owned_home": 1.55, "shared_rental": 0.45}, "中年阶段更可能形成稳定家庭住所。"),
	InfluenceRule("age_band", ("55+",), "living_situation", {"owned_home": 1.75, "with_family": 1.55, "partner_or_family_home": 1.35, "shared_rental": 0.25, "solo_rental": 0.7, "temporary_or_unstable": 0.45}, "55+ 更常见自有住房、家庭同住或稳定伴侣住所，合租和临时住所仍保留低概率。"),
	InfluenceRule("occupation_domain", ("retired",), "living_situation", {"owned_home": 1.55, "with_family": 1.35, "partner_or_family_home": 1.25, "shared_rental": 0.3, "temporary_or_unstable": 0.4}, "退休或半退休身份通常更依赖长期住所、家庭住所或积累住房。"),
	InfluenceRule("economic_status", ("struggling", "tight"), "living_situation", {"shared_rental": 1.45, "with_family": 1.35, "temporary_or_unstable": 1.65, "owned_home": 0.35}, "经济压力会提高合住、返家或临时居住概率。"),
	InfluenceRule("economic_status", ("comfortable", "affluent"), "living_situation", {"owned_home": 1.8, "solo_rental": 1.2, "temporary_or_unstable": 0.25}, "经济宽裕更容易支持独住或拥有住房。"),
	InfluenceRule("age_band", ("18-24",), "social_style", {"online_first": 1.7, "outgoing_connector": 1.2, "community_or_family_centered": 0.6}, "年轻人更容易以线上社交为重要入口。"),
	InfluenceRule("age_band", ("55+",), "social_style", {"community_or_family_centered": 1.8, "online_first": 0.55}, "55+ 更常围绕家庭、邻里或熟人社区组织社交。"),
	InfluenceRule("economic_status", ("struggling", "tight"), "consumption_style", {"budget_optimizer": 1.9, "value_practical": 1.35, "status_aware": 0.8, "experience_spender": 0.65}, "经济较紧时消费更重视预算和实用性。"),
	InfluenceRule("economic_status", ("comfortable", "affluent"), "consumption_style", {"experience_spender": 1.45, "status_aware": 1.35, "saver_investor": 1.25, "budget_optimizer": 0.55}, "经济宽裕提高体验、身份和投资型消费概率。"),
	InfluenceRule("social_style", ("online_first",), "media_style", {"short_video_scroller": 1.35, "gaming_streams": 1.55, "visual_lifestyle": 1.25, "quiet_low_media": 0.55}, "线上优先社交通常伴随更高平台内容消费。"),
	InfluenceRule("social_style", ("reserved_close_circle",), "media_style", {"longform_reader": 1.35, "podcast_audio": 1.2, "quiet_low_media": 1.25}, "内敛小圈层更可能偏长内容或低媒体强度。"),
)

INTEREST_RULES: tuple[InfluenceRule, ...] = (
	InfluenceRule("platform_archetype", ("private_social",), "practical_interests", {"home_cooking": 1.25, "walking_hiking": 1.15, "volunteering": 1.15, "video_games": 0.75}, "熟人社交内容更容易连到家庭、社区和日常活动。"),
	InfluenceRule("platform_archetype", ("short_video_mass",), "practical_interests", {"home_cooking": 1.25, "casual_fitness": 1.25, "crafts_making": 1.15, "video_games": 1.1}, "短视频平台提高可模仿、低门槛实践爱好的曝光。"),
	InfluenceRule("platform_archetype", ("public_discussion",), "practical_interests", {"reading_writing": 1.35, "photography": 1.1, "volunteering": 1.1}, "公共讨论平台更常连接表达、记录和议题参与。"),
	InfluenceRule("platform_archetype", ("lifestyle_discovery",), "practical_interests", {"photography": 1.45, "home_cooking": 1.35, "crafts_making": 1.25, "casual_fitness": 1.15, "diy_repairs": 0.75}, "生活方式发现平台提高审美化、展示型实践兴趣。"),
	InfluenceRule("platform_archetype", ("interest_community",), "practical_interests", {"video_games": 1.75, "music_making": 1.35, "reading_writing": 1.25, "diy_repairs": 1.15, "team_sports": 0.7}, "兴趣社区更偏游戏、创作、技术和长内容驱动的实践兴趣。"),
	InfluenceRule("economic_status", ("struggling", "tight"), "practical_interests", {"home_cooking": 1.45, "walking_hiking": 1.35, "video_games": 1.25, "diy_repairs": 1.3, "budget_travel": 1.2, "photography": 0.75, "team_sports": 0.8}, "经济压力让低成本、可在日常中实践的爱好更常见。"),
	InfluenceRule("economic_status", ("comfortable", "affluent"), "practical_interests", {"photography": 1.35, "team_sports": 1.25, "budget_travel": 1.4, "casual_fitness": 1.2, "home_cooking": 0.9}, "经济宽裕会提高装备型、出行型或课程型实践爱好。"),
	InfluenceRule("age_band", ("18-24",), "practical_interests", {"video_games": 1.65, "music_making": 1.25, "casual_fitness": 1.2, "gardening_plants": 0.55, "volunteering": 0.75}, "年轻成年人更偏游戏、音乐和低门槛运动。"),
	InfluenceRule("age_band", ("55+",), "practical_interests", {"gardening_plants": 1.75, "walking_hiking": 1.45, "volunteering": 1.4, "video_games": 0.35, "diy_repairs": 1.15}, "55+ 更常见园艺、散步和社区活动。"),
	InfluenceRule("social_style", ("outgoing_connector", "community_or_family_centered"), "practical_interests", {"team_sports": 1.45, "volunteering": 1.45, "home_cooking": 1.2}, "外向或社区型人格更容易选择和他人共同参与的活动。"),
	InfluenceRule("social_style", ("reserved_close_circle",), "practical_interests", {"reading_writing": 1.45, "crafts_making": 1.25, "gardening_plants": 1.15, "team_sports": 0.55}, "内敛小圈层更偏独处或低社交密度活动。"),
	InfluenceRule("economic_status", ("struggling", "tight"), "aspirational_interests", {"luxury_cars_watching": 1.15, "financial_freedom": 1.65, "esports_viewing": 1.25, "golf_culture_watching": 0.65, "fine_dining_watching": 0.75, "international_travel_watching": 0.9}, "经济压力不会阻止观赏性向往，但会压低高消费实践型文化的贴近度。"),
	InfluenceRule("economic_status", ("comfortable", "affluent"), "aspirational_interests", {"fine_dining_watching": 1.45, "international_travel_watching": 1.45, "golf_culture_watching": 1.35, "art_collecting_watching": 1.3, "luxury_cars_watching": 1.2}, "经济宽裕让高消费兴趣从纯观看更接近日常想象。"),
	InfluenceRule("age_band", ("18-24",), "aspirational_interests", {"esports_viewing": 1.7, "celebrity_culture": 1.35, "premium_tech": 1.25, "home_design": 0.65, "golf_culture_watching": 0.45}, "年轻人更偏线上娱乐、消费电子和流行文化。"),
	InfluenceRule("age_band", ("45-54", "55+"), "aspirational_interests", {"home_design": 1.35, "financial_freedom": 1.25, "golf_culture_watching": 1.2, "celebrity_culture": 0.55}, "中老年阶段更关注居住、资产和稳定生活想象。"),
	InfluenceRule("media_style", ("visual_lifestyle", "short_video_scroller"), "aspirational_interests", {"luxury_cars_watching": 1.25, "high_fashion_watching": 1.35, "fine_dining_watching": 1.2, "celebrity_culture": 1.25}, "视觉生活方式内容会放大身份消费和审美向往。"),
	InfluenceRule("platform_archetype", ("private_social",), "aspirational_interests", {"home_design": 1.35, "financial_freedom": 1.15, "celebrity_culture": 0.75, "esports_viewing": 0.7}, "熟人社交更容易放大家庭生活、居住和稳定感想象。"),
	InfluenceRule("platform_archetype", ("short_video_mass",), "aspirational_interests", {"luxury_cars_watching": 1.25, "celebrity_culture": 1.25, "premium_tech": 1.2, "financial_freedom": 1.15}, "短视频平台放大高可见度消费和成功叙事。"),
	InfluenceRule("platform_archetype", ("public_discussion",), "aspirational_interests", {"financial_freedom": 1.35, "premium_tech": 1.1, "celebrity_culture": 0.75}, "公共讨论平台更容易连到财富、职场和技术议题。"),
	InfluenceRule("platform_archetype", ("lifestyle_discovery",), "aspirational_interests", {"high_fashion_watching": 1.65, "fine_dining_watching": 1.45, "international_travel_watching": 1.35, "home_design": 1.3, "esports_viewing": 0.55}, "生活方式发现平台更强化审美、旅行和消费向往。"),
	InfluenceRule("platform_archetype", ("interest_community",), "aspirational_interests", {"esports_viewing": 1.7, "premium_tech": 1.45, "motorsport": 1.2, "high_fashion_watching": 0.65}, "兴趣社区更强化电竞、科技装备和垂直爱好观看。"),
	InfluenceRule("economic_status", ("struggling", "tight"), "high_cost_consumption_interests", {"luxury_car_purchase_planning": 0.04, "golf_membership": 0.03, "high_fashion_regular": 0.04, "fine_dining_regular": 0.04, "international_travel_regular": 0.03, "art_collecting_regular": 0.02}, "经济紧张时仍可关注高价对象，但真实高成本持续消费应极少。"),
	InfluenceRule("economic_status", ("comfortable",), "high_cost_consumption_interests", {"luxury_car_purchase_planning": 1.4, "golf_membership": 1.3, "fine_dining_regular": 1.45, "international_travel_regular": 1.35, "high_fashion_regular": 1.3}, "经济比较宽裕时，高成本消费兴趣可以少量出现。"),
	InfluenceRule("economic_status", ("affluent",), "high_cost_consumption_interests", {"luxury_car_purchase_planning": 4.0, "golf_membership": 4.0, "high_fashion_regular": 4.0, "fine_dining_regular": 4.0, "international_travel_regular": 4.2, "art_collecting_regular": 4.0}, "富裕用户更可能把部分高价兴趣转化为真实持续消费或计划。"),
	InfluenceRule("age_band", ("18-24",), "high_cost_consumption_interests", {"luxury_car_purchase_planning": 0.2, "golf_membership": 0.1, "art_collecting_regular": 0.15, "international_travel_regular": 0.35}, "年轻用户可以关注高价对象，但真实高成本持续消费更少。"),
	InfluenceRule("platform_archetype", ("lifestyle_discovery",), "high_cost_consumption_interests", {"high_fashion_regular": 1.4, "fine_dining_regular": 1.35, "international_travel_regular": 1.25}, "生活方式平台会提高高端时尚、餐饮和旅行消费的可见度。"),
)

FAMILY_RULES: tuple[InfluenceRule, ...] = (
	InfluenceRule("age_band", ("18-24",), "marital_status", {"single": 3.5, "dating": 1.6, "married": 0.18, "divorced": 0.04, "widowed": 0.01}, "18-24 更常见单身或恋爱，婚育状态保留极低概率。"),
	InfluenceRule("age_band", ("25-34",), "marital_status", {"single": 1.35, "dating": 1.2, "married": 1.2, "divorced": 0.55, "widowed": 0.05}, "25-34 在单身、恋爱和结婚之间分布更分散。"),
	InfluenceRule("age_band", ("35-44",), "marital_status", {"single": 0.55, "dating": 0.55, "married": 1.7, "divorced": 1.25, "widowed": 0.1}, "35-44 更常见稳定家庭，也保留离异概率。"),
	InfluenceRule("age_band", ("45-54",), "marital_status", {"single": 0.4, "dating": 0.45, "married": 1.75, "divorced": 1.35, "widowed": 0.25}, "45-54 更常见已婚、离异或长期家庭状态。"),
	InfluenceRule("age_band", ("55+",), "marital_status", {"single": 0.35, "dating": 0.25, "married": 1.5, "divorced": 1.15, "widowed": 1.4}, "55+ 的婚姻状态更偏长期伴侣、离异或丧偶。"),
	InfluenceRule("occupation_domain", ("student",), "marital_status", {"single": 2.0, "dating": 1.4, "married": 0.12, "divorced": 0.04, "widowed": 0.01}, "学生或刚进入社会阶段极少有复杂婚姻状态。"),
	InfluenceRule("age_band", ("18-24",), "children_status", {"no_children": 7.0, "young_children": 0.08, "school_age_children": 0.01, "adult_children": 0.001}, "18-24 有成年子女属于明显反常识组合，应压到极低。"),
	InfluenceRule("age_band", ("25-34",), "children_status", {"no_children": 1.8, "young_children": 1.5, "school_age_children": 0.45, "adult_children": 0.01}, "25-34 可有幼儿，成年子女极少。"),
	InfluenceRule("age_band", ("35-44",), "children_status", {"no_children": 0.8, "young_children": 1.3, "school_age_children": 1.8, "adult_children": 0.08}, "35-44 更常见幼儿或学龄子女。"),
	InfluenceRule("age_band", ("45-54",), "children_status", {"no_children": 0.65, "young_children": 0.25, "school_age_children": 1.4, "adult_children": 1.3}, "45-54 更常见学龄或成年子女。"),
	InfluenceRule("age_band", ("55+",), "children_status", {"no_children": 0.55, "young_children": 0.03, "school_age_children": 0.2, "adult_children": 2.4}, "55+ 更常见成年子女。"),
	InfluenceRule("marital_status", ("single", "dating"), "children_status", {"no_children": 2.2, "young_children": 0.25, "school_age_children": 0.22, "adult_children": 0.55}, "单身或恋爱不排除孩子，但概率低于已婚/离异。"),
	InfluenceRule("marital_status", ("married",), "children_status", {"young_children": 1.4, "school_age_children": 1.35, "adult_children": 1.2}, "已婚状态更常和子女状态同时出现。"),
	InfluenceRule("marital_status", ("divorced", "widowed"), "children_status", {"school_age_children": 1.2, "adult_children": 1.25, "no_children": 0.8}, "离异或丧偶状态可以伴随学龄或成年子女。"),
	InfluenceRule("occupation_domain", ("student",), "children_status", {"no_children": 3.0, "young_children": 0.08, "school_age_children": 0.02, "adult_children": 0.01}, "学生和孩子状态组合应非常少见。"),
	InfluenceRule("age_band", ("18-24",), "parent_support", {"no_parent_support": 2.4, "supports_parents_lightly": 0.55, "supports_parents_heavily": 0.08, "caregiver_for_elder": 0.05}, "18-24 通常还未形成固定赡养责任。"),
	InfluenceRule("age_band", ("35-44", "45-54"), "parent_support", {"supports_parents_lightly": 1.5, "supports_parents_heavily": 1.25, "caregiver_for_elder": 1.35}, "中年阶段更常承担父母支持或照护。"),
	InfluenceRule("economic_status", ("struggling", "tight"), "parent_support", {"supports_parents_heavily": 1.45, "caregiver_for_elder": 1.25}, "经济压力和家庭支持责任可能叠加。"),
	InfluenceRule("economic_status", ("affluent",), "parent_support", {"supports_parents_heavily": 0.55, "caregiver_for_elder": 0.7}, "富裕状态下较重照护压力仍可能存在，但权重较低。"),
	InfluenceRule("children_status", ("young_children", "school_age_children"), "family_burden", {"moderate_family_responsibility": 1.9, "heavy_family_responsibility": 1.7, "low_family_responsibility": 0.65}, "幼儿或学龄子女提高家庭责任。"),
	InfluenceRule("parent_support", ("supports_parents_heavily", "caregiver_for_elder"), "family_burden", {"moderate_family_responsibility": 1.6, "heavy_family_responsibility": 2.5, "low_family_responsibility": 0.45}, "较重赡养或照护提高家庭负担。"),
	InfluenceRule("economic_status", ("struggling", "tight"), "family_burden", {"heavy_family_responsibility": 1.8, "moderate_family_responsibility": 1.2, "low_family_responsibility": 0.7}, "经济压力会放大家庭责任感。"),
	InfluenceRule("economic_status", ("affluent",), "family_burden", {"heavy_family_responsibility": 0.45, "low_family_responsibility": 1.25}, "富裕状态下家庭责任可能存在，但不宜大面积沉重化。"),
)

BIG_FIVE_BASE: dict[str, float] = {"openness": 0.5, "conscientiousness": 0.5, "extraversion": 0.5, "agreeableness": 0.5, "neuroticism": 0.5}

BIG_FIVE_RULES: dict[str, dict[str, dict[str, float]]] = {
	"education": {"graduate": {"openness": 0.12, "conscientiousness": 0.05}, "self_taught": {"openness": 0.10}},
	"occupation_domain": {
		"technical": {"conscientiousness": 0.08},
		"creative_media": {"openness": 0.12},
		"care_education": {"agreeableness": 0.12},
		"small_business": {"conscientiousness": 0.06, "neuroticism": 0.04},
	},
	"economic_status": {"struggling": {"neuroticism": 0.12}, "tight": {"neuroticism": 0.07}, "comfortable": {"neuroticism": -0.05}, "affluent": {"neuroticism": -0.07}},
	"social_style": {
		"reserved_close_circle": {"extraversion": -0.18},
		"warm_small_group": {"agreeableness": 0.08},
		"outgoing_connector": {"extraversion": 0.20},
		"online_first": {"extraversion": -0.04, "openness": 0.05},
		"community_or_family_centered": {"agreeableness": 0.12},
	},
}

PROFILE_ORDER = ("platform_archetype", "age_band", "education", "occupation_domain", "economic_status", "living_situation", "social_style", "media_style", "consumption_style")


def _clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
	return max(float(min_value), min(float(max_value), float(value)))


def _weighted_choice(rng: random.Random, weights: WeightedOptions) -> str:
	total = sum(max(0.0, float(v)) for v in weights.values())
	if total <= 0:
		raise ValueError("weighted choice requires positive total weight")
	roll = rng.uniform(0.0, total)
	upto = 0.0
	last_key = ""
	for key, weight in weights.items():
		last_key = key
		upto += max(0.0, float(weight))
		if roll <= upto:
			return key
	return last_key


def _sample_many(rng: random.Random, weights: WeightedOptions, count: int) -> list[str]:
	pool = dict(weights)
	out: list[str] = []
	for _ in range(max(0, int(count))):
		if not pool:
			break
		chosen = _weighted_choice(rng, pool)
		out.append(chosen)
		pool.pop(chosen, None)
	return out


def _apply_rules(base: WeightedOptions, field: str, profile: dict[str, Any], rules: tuple[InfluenceRule, ...]) -> tuple[WeightedOptions, list[dict[str, Any]]]:
	weights = {str(k): float(v) for k, v in base.items()}
	trace: list[dict[str, Any]] = []
	for rule in rules:
		if rule.target_field != field or not rule.matches(profile):
			continue
		applied: dict[str, float] = {}
		for option, multiplier in rule.multipliers.items():
			if option not in weights:
				continue
			weights[option] = max(0.0001, weights[option] * float(multiplier))
			applied[option] = float(multiplier)
		if applied:
			trace.append({"field": field, "source_field": rule.source_field, "source_value": str(profile.get(rule.source_field, "")), "multipliers": applied, "reason": rule.reason})
	return weights, trace


def _label_list(keys: list[str]) -> list[dict[str, str]]:
	return [{"id": key, "label": INTEREST_LABELS.get(key, key)} for key in keys]


def _category_label(field: str, value: Any) -> str:
	value_s = str(value or "")
	return CATEGORY_LABELS.get(field, {}).get(value_s, value_s)


def _specific_choice(rng: random.Random, field: str, category: str) -> str:
	options = SPECIFIC_OPTIONS.get(field, {}).get(str(category), [])
	if not options:
		return _category_label(field, category)
	return str(rng.choice(options))


def _specific_base_weights(field: str, category: str) -> WeightedOptions:
	weighted = SPECIFIC_VALUE_WEIGHTS.get(field, {}).get(str(category))
	if weighted:
		return dict(weighted)
	options = SPECIFIC_OPTIONS.get(field, {}).get(str(category), [])
	if not options:
		return {_category_label(field, category): 1.0}
	return {str(option): 1.0 for option in options}


def _specific_interest(rng: random.Random, interest_id: str) -> str:
	options = SPECIFIC_INTERESTS.get(str(interest_id), [])
	if not options:
		return INTEREST_LABELS.get(str(interest_id), str(interest_id))
	return str(rng.choice(options))


def _sample_family_field(rng: random.Random, field: str, profile: dict[str, Any], extra_rules: tuple[InfluenceRule, ...]) -> tuple[str, dict[str, float], list[dict[str, Any]]]:
	base = FAMILY_WEIGHTS[field]
	weights, trace = _apply_rules(base, field, profile, extra_rules)
	return _weighted_choice(rng, weights), {k: round(v, 4) for k, v in weights.items()}, trace


def _family_label(field: str, value: str) -> str:
	labels = {
		"marital_status": {
			"single": "单身",
			"dating": "恋爱中",
			"married": "已婚",
			"divorced": "离异",
			"widowed": "丧偶",
		},
		"children_status": {
			"no_children": "无子女",
			"young_children": "有幼儿",
			"school_age_children": "有学龄子女",
			"adult_children": "有成年子女",
		},
		"parent_support": {
			"no_parent_support": "无固定赡养支持",
			"supports_parents_lightly": "轻度支持父母",
			"supports_parents_heavily": "较重支持父母",
			"caregiver_for_elder": "照顾年迈长辈",
		},
		"family_burden": {
			"low_family_responsibility": "家庭责任较轻",
			"moderate_family_responsibility": "家庭责任中等",
			"heavy_family_responsibility": "家庭责任较重",
		},
	}
	return labels.get(field, {}).get(value, value)


class SocialProfileSampler:
	def __init__(self, seed: int | str | None = None):
		self.rng = random.Random(seed)

	def sample_profile(self, index: int = 0, include_debug: bool = False) -> dict[str, Any]:
		sample: dict[str, Any] = {}
		trace: list[dict[str, Any]] = []
		weights_debug: dict[str, dict[str, float]] = {}

		sample["platform_archetype"] = _weighted_choice(self.rng, PLATFORM_ARCHETYPES)
		weights_debug["platform_archetype"] = {k: round(v, 4) for k, v in PLATFORM_ARCHETYPES.items()}
		trace.append({"field": "platform_archetype", "reason": "aggregate social platform mix prior", "weights": dict(PLATFORM_ARCHETYPES)})

		age_weights, age_trace = _apply_rules(AGE_BANDS, "age_band", sample, PLATFORM_INFLUENCE_RULES)
		trace.extend(age_trace)
		sample["age_band"] = _weighted_choice(self.rng, age_weights)
		weights_debug["age_band"] = {k: round(v, 4) for k, v in age_weights.items()}

		for field in PROFILE_ORDER:
			if field in {"platform_archetype", "age_band"}:
				continue
			platform_weights, platform_trace = _apply_rules(BASE_WEIGHTS[field], field, sample, PLATFORM_INFLUENCE_RULES)
			weights, field_trace = _apply_rules(platform_weights, field, sample, INFLUENCE_RULES)
			trace.extend(platform_trace)
			trace.extend(field_trace)
			sample[field] = _weighted_choice(self.rng, weights)
			weights_debug[field] = {k: round(v, 4) for k, v in weights.items()}

		practical_weights, practical_trace = _apply_rules(PRACTICAL_INTERESTS, "practical_interests", sample, INTEREST_RULES)
		aspirational_weights, aspirational_trace = _apply_rules(ASPIRATIONAL_INTERESTS, "aspirational_interests", sample, INTEREST_RULES)
		high_cost_weights, high_cost_trace = _apply_rules(HIGH_COST_CONSUMPTION_INTERESTS, "high_cost_consumption_interests", sample, INTEREST_RULES)
		trace.extend(practical_trace)
		trace.extend(aspirational_trace)
		trace.extend(high_cost_trace)
		weights_debug["practical_interests"] = {k: round(v, 4) for k, v in practical_weights.items()}
		weights_debug["aspirational_interests"] = {k: round(v, 4) for k, v in aspirational_weights.items()}
		weights_debug["high_cost_consumption_interests"] = {k: round(v, 4) for k, v in high_cost_weights.items()}
		sample["practical_interests"] = _label_list(_sample_many(self.rng, practical_weights, self.rng.randint(2, 3)))
		sample["aspirational_interests"] = _label_list(_sample_many(self.rng, aspirational_weights, self.rng.randint(1, 2)))
		high_cost_count = 1 if self.rng.random() < self._high_cost_interest_probability(sample) else 0
		sample["high_cost_consumption_interests"] = _label_list(_sample_many(self.rng, high_cost_weights, high_cost_count))
		sample["family_profile"], family_weights_debug, family_trace = self._sample_family_profile(sample)
		weights_debug.update(family_weights_debug)
		trace.extend(family_trace)
		sample["big_five"] = self._sample_big_five(sample)
		sample["specifics"], specific_weights_debug, specific_trace = self._sample_specifics(sample)
		weights_debug.update(specific_weights_debug)
		trace.extend(specific_trace)

		display = {field: _category_label(field, sample.get(field, "")) for field in PROFILE_ORDER}
		profile: dict[str, Any] = {
			"profile_id": f"social_profile_{int(index):03d}",
			"sample": sample,
			"display": display,
			"summary_line": f"{display['age_band']}，{display['occupation_domain']}，偏{display['platform_archetype']}用户，经济状态{display['economic_status']}。",
			"interest_notes": [
			"practical_interests are activities the account owner plausibly does or has done.",
			"aspirational_interests are things the account owner may follow, admire, watch, or fantasize about without regularly practicing.",
			"high_cost_consumption_interests are actual high-cost habits or plans; they should stay rare and require stronger economic support.",
			],
		}
		profile["llm_background_prompt"] = build_llm_background_prompt(profile)
		if include_debug:
			profile["debug"] = {
				"sampling_trace": trace,
				"weights": weights_debug,
			}
		return profile

	def _sample_big_five(self, profile: dict[str, Any]) -> dict[str, float]:
		values = {k: v + self.rng.uniform(-0.22, 0.22) for k, v in BIG_FIVE_BASE.items()}
		for field, option_rules in BIG_FIVE_RULES.items():
			selected = str(profile.get(field, ""))
			for dimension, delta in option_rules.get(selected, {}).items():
				values[dimension] = values.get(dimension, 0.5) + float(delta)
		return {key: round(_clamp(value), 1) for key, value in values.items()}

	def _specific_occupation(self, sample: dict[str, Any]) -> tuple[str, dict[str, float], list[dict[str, Any]]]:
		domain = str(sample.get("occupation_domain", ""))
		base = SPECIFIC_OCCUPATION_WEIGHTS.get(domain)
		if not base:
			value = _specific_choice(self.rng, "occupation_domain", domain)
			return value, {value: 1.0}, []
		weights, trace = _apply_rules(base, "specific_occupation", sample, SPECIFIC_OCCUPATION_RULES)
		return _weighted_choice(self.rng, weights), {k: round(v, 4) for k, v in weights.items()}, trace

	def _specific_value(self, sample: dict[str, Any], field: str, category: str, target_field: str) -> tuple[str, dict[str, float], list[dict[str, Any]]]:
		base = _specific_base_weights(field, category)
		weights, trace = _apply_rules(base, target_field, sample, SPECIFIC_VALUE_RULES)
		return _weighted_choice(self.rng, weights), {k: round(v, 4) for k, v in weights.items()}, trace

	def _high_cost_interest_probability(self, sample: dict[str, Any]) -> float:
		economic = str(sample.get("economic_status", ""))
		platform = str(sample.get("platform_archetype", ""))
		prob = {
			"struggling": 0.01,
			"tight": 0.02,
			"stable": 0.05,
			"comfortable": 0.16,
			"affluent": 0.34,
		}.get(economic, 0.04)
		if platform == "lifestyle_discovery":
			prob *= 1.25
		if str(sample.get("age_band", "")) == "18-24":
			prob *= 0.45
		return _clamp(prob, 0.0, 0.55)

	def _sample_family_profile(self, sample: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, float]], list[dict[str, Any]]]:
		family: dict[str, str] = {}
		weights_debug: dict[str, dict[str, float]] = {}
		trace: list[dict[str, Any]] = []
		for field in ["marital_status", "children_status", "parent_support", "family_burden"]:
			context = dict(sample)
			context.update(family)
			value, weights, field_trace = _sample_family_field(self.rng, field, context, FAMILY_RULES)
			family[field] = value
			weights_debug[f"family_{field}"] = weights
			trace.extend(field_trace)
		family["labels"] = {
			"marital_status": _family_label("marital_status", family["marital_status"]),
			"children_status": _family_label("children_status", family["children_status"]),
			"parent_support": _family_label("parent_support", family["parent_support"]),
			"family_burden": _family_label("family_burden", family["family_burden"]),
		}
		return family, weights_debug, trace

	def _sample_specifics(self, sample: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, float]], list[dict[str, Any]]]:
		age_min, age_max = AGE_RANGES.get(str(sample.get("age_band", "")), (25, 34))
		occupation, occupation_weights, occupation_trace = self._specific_occupation(sample)
		education, education_weights, education_trace = self._specific_value(sample, "education", str(sample.get("education", "")), "specific_education")
		living, living_weights, living_trace = self._specific_value(sample, "living_situation", str(sample.get("living_situation", "")), "specific_living_situation")
		media, media_weights, media_trace = self._specific_value(sample, "media_style", str(sample.get("media_style", "")), "specific_media_habit")
		consumption, consumption_weights, consumption_trace = self._specific_value(sample, "consumption_style", str(sample.get("consumption_style", "")), "specific_consumption_habit")
		practical = []
		for item in list(sample.get("practical_interests", []) or []):
			if not isinstance(item, dict):
				continue
			interest_id = str(item.get("id", "") or "")
			practical.append({"id": interest_id, "label": str(item.get("label", "") or ""), "specific": _specific_interest(self.rng, interest_id)})
		aspirational = []
		for item in list(sample.get("aspirational_interests", []) or []):
			if not isinstance(item, dict):
				continue
			interest_id = str(item.get("id", "") or "")
			aspirational.append({"id": interest_id, "label": str(item.get("label", "") or ""), "specific": _specific_interest(self.rng, interest_id)})
		high_cost = []
		for item in list(sample.get("high_cost_consumption_interests", []) or []):
			if not isinstance(item, dict):
				continue
			interest_id = str(item.get("id", "") or "")
			high_cost.append({"id": interest_id, "label": str(item.get("label", "") or ""), "specific": _specific_interest(self.rng, interest_id)})
		return {
			"age": self.rng.randint(int(age_min), int(age_max)),
			"education": education,
			"occupation": occupation,
			"living_situation": living,
			"media_habit": media,
			"consumption_habit": consumption,
			"practical_interests": practical,
			"aspirational_interests": aspirational,
			"high_cost_consumption_interests": high_cost,
		}, {
			"specific_education": education_weights,
			"specific_occupation": occupation_weights,
			"specific_living_situation": living_weights,
			"specific_media_habit": media_weights,
			"specific_consumption_habit": consumption_weights,
		}, occupation_trace + education_trace + living_trace + media_trace + consumption_trace


def generate_social_profiles(count: int = 100, seed: int | str | None = None, include_debug: bool = False) -> list[dict[str, Any]]:
	sampler = SocialProfileSampler(seed=seed)
	return [sampler.sample_profile(i + 1, include_debug=include_debug) for i in range(int(count))]


def _interest_labels(items: list[dict[str, str]]) -> str:
	return "、".join(str(x.get("label", x.get("id", ""))) for x in list(items or []) if isinstance(x, dict))


def _specific_interest_text(specifics: dict[str, Any], kind: str) -> str:
	return "、".join(
		str(x.get("specific", x.get("label", "")))
		for x in list(specifics.get(kind, []) or [])
		if isinstance(x, dict)
	)


def build_llm_background_prompt(profile: dict[str, Any]) -> str:
	sample = dict(profile.get("sample", {}) or {})
	big_five = dict(sample.get("big_five", {}) or {})
	specifics = dict(sample.get("specifics", {}) or {})
	display = dict(profile.get("display", {}) or {})
	family = dict(sample.get("family_profile", {}) or {})
	family_labels = dict(family.get("labels", {}) or {})
	practical_specifics = _specific_interest_text(specifics, "practical_interests")
	aspirational_specifics = _specific_interest_text(specifics, "aspirational_interests")
	high_cost_specifics = _specific_interest_text(specifics, "high_cost_consumption_interests")
	if not high_cost_specifics:
		high_cost_specifics = "无"
	return (
		"请根据以下结构化采样，为一个社交平台账号背后的模拟 agent 写一份中文自然语言角色背景。"
		"采样是约束而不是逐字模板；可以自由补充细节，但整体要大致符合。\n\n"
		"输出要求：\n"
		"- 只输出自然语言正文，不要分栏，不要项目符号，不要使用“姓名：”“年龄段：”“经济状态：”“大五人格：”这类标签。\n"
		"- 不要直接写出抽象分类 id 或心理测量标签，例如 openness、conscientiousness、social_style、economic_status。\n"
		"- 要把年龄、生活压力、社交习惯、兴趣和性格倾向融入叙述，让读者通过细节感受到这些设定。\n"
		"- 可以给角色起一个自然的中文姓名，但姓名也要融进句子里，不要单独作为字段。\n"
		"- 写 2 到 4 段，总长度适中，适合作为 agent 的背景设定文本。\n\n"
		"硬性约束：\n"
		"- 职业/身份、家庭关系、兴趣爱好必须保持各自独立；不要把两个字段柔和成一个新事实。\n"
		"- 例如 small_business_owner + street_food 不能被写成“路边摊小贩”，除非具体职业/身份本身就是相关职业；service_retail + 美妆兴趣也不能自动写成美妆从业者。\n"
		"- 观赏性/向往型兴趣只表示会关注、收藏、观看、想象或讨论，不等于已经拥有、经常消费或具备相应资产。\n"
		"- 高成本持续消费/计划兴趣才可以写成真实高价消费习惯或明确购买计划；如果为“无”，不要补出豪车、会员、高端旅行等持续消费事实。\n"
		"- 健康、医学、心理、养老等相关兴趣只能写成内容关注或日常经验，不要推导出本人患病、家人患病或职业身份。\n"
		"- 家庭结构以采样信息为准，不要额外发明婚姻变故、配偶职业、子女疾病、债务来源等强情节。\n\n"
		"采样信息：\n"
		f"- 平台使用倾向：{display.get('platform_archetype', sample.get('platform_archetype'))}\n"
		f"- 年龄段：{display.get('age_band', sample.get('age_band'))}\n"
		f"- 确定年龄：{specifics.get('age')}\n"
		f"- 教育背景：{display.get('education', sample.get('education'))}\n"
		f"- 具体教育经历：{specifics.get('education')}\n"
		f"- 职业/生活领域：{display.get('occupation_domain', sample.get('occupation_domain'))}\n"
		f"- 具体职业/身份：{specifics.get('occupation')}\n"
		f"- 经济状态：{display.get('economic_status', sample.get('economic_status'))}\n"
		f"- 居住状态：{display.get('living_situation', sample.get('living_situation'))}\n"
		f"- 具体居住处境：{specifics.get('living_situation')}\n"
		f"- 家庭结构：{family_labels.get('marital_status', family.get('marital_status'))}，{family_labels.get('children_status', family.get('children_status'))}，{family_labels.get('parent_support', family.get('parent_support'))}，{family_labels.get('family_burden', family.get('family_burden'))}\n"
		f"- 社交风格：{display.get('social_style', sample.get('social_style'))}\n"
		f"- 媒体偏好：{display.get('media_style', sample.get('media_style'))}\n"
		f"- 具体媒体习惯：{specifics.get('media_habit')}\n"
		f"- 消费风格：{display.get('consumption_style', sample.get('consumption_style'))}\n"
		f"- 具体消费习惯：{specifics.get('consumption_habit')}\n"
		f"- 大五人格：开放性 {big_five.get('openness')}, 尽责性 {big_five.get('conscientiousness')}, 外向性 {big_five.get('extraversion')}, 宜人性 {big_five.get('agreeableness')}, 神经质 {big_five.get('neuroticism')}\n"
		f"- 实操性爱好大类：{_interest_labels(list(sample.get('practical_interests', []) or []))}\n"
		f"- 实操性爱好具体表现：{practical_specifics}\n"
		f"- 观赏性/向往型兴趣大类：{_interest_labels(list(sample.get('aspirational_interests', []) or []))}\n"
		f"- 观赏性/向往型兴趣具体表现：{aspirational_specifics}\n"
		f"- 高成本持续消费/计划兴趣：{_interest_labels(list(sample.get('high_cost_consumption_interests', []) or [])) or '无'}\n"
		f"- 高成本持续消费/计划具体表现：{high_cost_specifics}\n"
	)
