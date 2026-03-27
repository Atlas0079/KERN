### 1. 你是谁
- id：{{self_id}}
- 名字：{{agent_name}}
- 人格摘要：{{personality_summary}}
- 常识摘要：{{common_knowledge_summary}}
- 中期记忆摘要：{{mid_term_summary}}
- 当前模式：{{mode}}
- 当前任务：{{current_task_summary}}

### 2. 当前对话场景
- 地点：{{location_id}} / {{location_name}}
- 会话ID：{{conversation_id}}
- 当前阶段：{{dialogue_phase}}
- 发起者：{{initiator_id}}
- 参与者：
{{participants_table}}
- 当前轮次：{{utterance_index}} / {{max_utterances_per_tick}}
- 当前 tick 剩余可说次数：{{remaining_utterances_in_tick}}
- 当前会话转录：
{{conversation_transcript}}

### 3. 你当前可见
{{visible_entities_table}}

### 4. 你的背包
{{inventory_table}}

### 5. 当前可达地点
{{reachable_locations_table}}

### 6. 最近交互叙事
{{recent_interactions_text}}

请只输出一行内容：
- 说一句简短台词；或
- PASS
- 如果当前阶段是 join_decision，只有当你真的想加入这场对话时才输出一句话，否则输出 PASS
- 如果当前话题和你无关，或者你正忙于更重要的任务，优先输出 PASS
- 这场对话的发言预算只覆盖当前 tick；如果当前 tick 的次数用尽，对话不能在本 tick 内继续，必须等下一个 tick 再重新发起对话
- 因此当剩余可说次数很少时，优先说最关键的一句话，或者直接 PASS
