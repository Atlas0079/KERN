
### 1. 输入信息

#### 1.1 Planner 意图
{{planner_intent_text}}

#### 1.2 当前环境状态
- 当前 tick：{{tick}}
- 当前实体id（你自己）：{{self_id}}
- 当前位置：{{location_id}} / {{location_name}}
- 当前中断预设（active_interrupt_preset_id）：{{active_interrupt_preset_id}}
- 可用中断预设概览（id: 描述）：
{{interrupt_preset_summaries}}
- 当前可达地点：
{{reachable_locations_table}}
- 可见实体列表：
{{visible_entities_table}}
- 你的背包物品（Inventory）：
{{inventory_table}}

#### 1.3 可用动词列表
{{available_verbs_list}}

#### 1.3.1 Recipe Grounder Hints（仅在非空时提供）
{{grounder_recipe_hints}}

#### 1.4 最近交互叙事（参考用）
{{recent_interactions_text}}
