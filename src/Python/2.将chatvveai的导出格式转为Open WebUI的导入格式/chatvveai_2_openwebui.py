import json
import uuid
from datetime import datetime

# ================= 配置区域 =================
INPUT_FILE = "export.json"    # 你的原始导出文件名
OUTPUT_FILE = "openwebui_import.json"  # 转换后的输出文件名
# ============================================

def parse_time_to_timestamp(time_str):
    """将日期字符串转换为Unix时间戳 (秒)"""
    try:
        # 匹配示例格式: "2026/2/3 14:08:18" 或 "2026/02/03 14:08:18"
        dt = datetime.strptime(time_str, "%Y/%m/%d %H:%M:%S")
        return int(dt.timestamp())
    except Exception as e:
        # 如果解析失败，使用当前时间戳
        return int(datetime.now().timestamp())

def find_conversations(data):
    """自动在 JSON 结构中寻找包含对话数据的数组"""
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                # 识别特征：包含 'data' 且 'data' 是列表
                if 'data' in value[0] and isinstance(value[0]['data'], list):
                    return value
            # 递归查找
            found = find_conversations(value)
            if found: return found
    elif isinstance(data, list):
        if len(data) > 0 and isinstance(data[0], dict) and 'data' in data[0]:
            return data
        for item in data:
            found = find_conversations(item)
            if found: return found
    return []

def convert():
    print(f"正在读取文件: {INPUT_FILE} ...")
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            source_data = json.load(f)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {INPUT_FILE}，请确保文件名和路径正确！")
        return

    # 提取原始对话列表
    raw_conversations = find_conversations(source_data)
    if not raw_conversations:
        print("错误: 在JSON中未找到符合特征的对话数据。请检查文件格式。")
        return

    openwebui_export = []

    print(f"找到 {len(raw_conversations)} 条历史对话，开始转换...")

    for conv in raw_conversations:
        chat_id = str(uuid.uuid4())
        messages_array = []
        history_dict = {"messages": {}, "currentId": None}
        models_used = set()
        
        raw_msgs = conv.get('data', [])
        if not raw_msgs:
            continue

        created_at = None
        updated_at = None
        title = "导入的新对话"
        parent_id = None

        for idx, msg in enumerate(raw_msgs):
            # ===== 新增修复：跳过 null 或非字典的异常数据 =====
            if not isinstance(msg, dict):
                continue
            # ==================================================

            msg_id = str(uuid.uuid4())
            timestamp = parse_time_to_timestamp(msg.get('dateTime', ''))
            
            if created_at is None:
                created_at = timestamp
            updated_at = timestamp

            # 判定角色: inversion: true 为 user，false 为 assistant
            role = "user" if msg.get('inversion', False) else "assistant"
            content = msg.get('text', '')

            # 获取模型名称
            model_name = msg.get('model', '')
            if role == "assistant" and model_name:
                models_used.add(model_name)

            # 使用第一条用户消息截断作为标题
            if idx == 0 and role == "user":
                title = (content[:30] + '...') if len(content) > 30 else content

            # 构建 OpenWebUI 消息树节点
            history_msg = {
                "id": msg_id,
                "parentId": parent_id,
                "childrenIds": [],
                "role": role,
                "content": content,
                "timestamp": timestamp
            }
            if role == "assistant" and model_name:
                history_msg["model"] = model_name

            # 更新父节点的 childrenIds
            if parent_id is not None:
                history_dict["messages"][parent_id]["childrenIds"].append(msg_id)

            history_dict["messages"][msg_id] = history_msg
            
            # 同时推入简化的消息数组
            messages_array.append({
                "id": msg_id,
                "role": role,
                "content": content
            })

            parent_id = msg_id

        # 最后一个消息设置为 currentId
        history_dict["currentId"] = parent_id

        # 如果整条对话都是空的（全被跳过），则不导入这条对话
        if not messages_array:
            continue

        # 组装为 OpenWebUI 需要的单条 Chat 对象
        if not models_used:
            models_used.add("imported-model")

        openwebui_chat = {
            "id": chat_id,
            "title": title,
            "created_at": created_at,
            "updated_at": updated_at,
            "chat": {
                "id": chat_id,
                "title": title,
                "models": list(models_used),
                "messages": messages_array,
                "history": history_dict
            }
        }
        
        openwebui_export.append(openwebui_chat)

    # 写入新文件
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(openwebui_export, f, ensure_ascii=False, indent=2)

    print(f"转换成功！共转换了 {len(openwebui_export)} 条对话。")
    print(f"请前往 OpenWebUI 的设置(Settings) -> 工作区(Workspace) / 聊天(Chats) -> 导入(Import) 使用文件: {OUTPUT_FILE}")

if __name__ == "__main__":
    convert()