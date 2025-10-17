import os
import sys
import json
import time
import subprocess
from flask import Flask, request, jsonify
import requests

# 将当前目录添加到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)

# 钉钉机器人配置
DINGTALK_ROBOT_TOKEN = "02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"
DINGTALK_WEBHOOK = f"https://oapi.dingtalk.com/robot/send?access_token={DINGTALK_ROBOT_TOKEN}"

# 用于验证钉钉消息的密钥（如果设置了加签）
# 请根据实际配置设置此值
SECRET = ""

# 支持的指令列表
SUPPORTED_COMMANDS = {
    "分析": "运行完整分析",
    "帮助": "显示帮助信息",
    "状态": "显示系统状态",
    "退出": "停止服务"
}

@app.route('/dingtalk/callback', methods=['POST'])
def dingtalk_callback():
    """接收钉钉回调并处理指令"""
    try:
        # 获取请求数据
        data = request.json
        print(f"收到钉钉消息: {data}")
        
        # 检查消息类型
        if data.get('msgtype') != 'text':
            return jsonify({"errcode": 0, "errmsg": "success"})
        
        # 获取消息内容
        message = data.get('text', {}).get('content', '').strip()
        if not message:
            return jsonify({"errcode": 0, "errmsg": "success"})
        
        # 处理指令
        response = process_command(message)
        
        # 将处理结果发送回钉钉群
        send_to_dingtalk(response)
        
        return jsonify({"errcode": 0, "errmsg": "success"})
    
    except Exception as e:
        print(f"处理钉钉回调出错: {e}")
        return jsonify({"errcode": 500, "errmsg": str(e)})

def process_command(command):
    """处理钉钉群发送的指令"""
    command = command.lower().strip()
    
    if command == "分析" or command == "运行" or command.startswith("run"):
        return run_analysis()
    elif command == "帮助" or command == "help":
        return show_help()
    elif command == "状态" or command == "status":
        return show_status()
    elif command == "退出" or command == "quit" or command == "exit":
        return "服务将在3秒后停止..."
    else:
        return f"未知指令: {command}\n输入'帮助'查看支持的指令"

def run_analysis():
    """运行加密货币分析脚本"""
    try:
        send_to_dingtalk("开始运行分析，请稍候...")
        
        # 运行主分析脚本
        result = subprocess.run(
            [sys.executable, "crypto_multiperiod_analysis.py"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            timeout=300  # 设置5分钟超时
        )
        
        output = result.stdout
        error = result.stderr
        
        # 构建响应消息
        response = "### 分析完成\n\n"
        
        # 提取关键信息（如果输出太长）
        if len(output) > 500:
            # 查找分析完成的部分
            if "分析完成" in output:
                analysis_summary = output.split("分析完成", 1)[1]
                response += "### 分析结果摘要\n"
                response += f"```\n{analysis_summary}\n```\n"
                
                # 查找卖出信号部分
                if "卖出信号币种" in output:
                    sell_part = output.split("卖出信号币种", 1)[1].split("\n", 2)[1]
                    response += f"### 卖出信号数量\n{sell_part}\n"
                
                response += "\n💡 分析已完成，详细日志可在服务器查看"
            else:
                response += "分析已运行，但未找到完整结果"
        else:
            response += f"```\n{output}\n```"
        
        if error:
            response += f"\n⚠️ 运行过程中有错误:\n```\n{error}\n```"
        
        return response
        
    except subprocess.TimeoutExpired:
        return "⚠️ 分析超时（超过5分钟）"
    except Exception as e:
        return f"⚠️ 运行分析时出错: {str(e)}"

def show_help():
    """显示帮助信息"""
    help_text = "### 支持的指令\n\n"
    for cmd, desc in SUPPORTED_COMMANDS.items():
        help_text += f"- **{cmd}**: {desc}\n"
    
    help_text += "\n### 使用示例\n- 在钉钉群中发送'分析'，系统将运行完整的加密货币分析\n- 发送'帮助'查看此帮助信息\n- 发送'状态'查看系统状态"
    
    return help_text

def show_status():
    """显示系统状态"""
    status = "### 系统状态\n\n"
    status += f"- **服务运行状态**: 正常\n"
    status += f"- **当前时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
    status += f"- **Python版本**: {sys.version.split()[0]}\n"
    status += f"- **支持指令数**: {len(SUPPORTED_COMMANDS)}\n"
    
    return status

def send_to_dingtalk(message, title="加密货币分析机器人"):
    """发送消息到钉钉群"""
    try:
        headers = {'Content-Type': 'application/json;charset=utf-8'}
        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": message
            }
        }
        
        response = requests.post(DINGTALK_WEBHOOK, headers=headers, json=data)
        if response.status_code == 200 and response.json().get('errcode') == 0:
            print("消息发送成功")
            return True
        else:
            print(f"消息发送失败: {response.text}")
            return False
    except Exception as e:
        print(f"发送消息时出错: {e}")
        return False

def main():
    """主函数"""
    print("钉钉交互式分析服务器启动中...")
    print("支持的指令:", " | ".join(SUPPORTED_COMMANDS.keys()))
    print("请确保在钉钉机器人设置中配置正确的回调地址")
    print("服务器将在 http://0.0.0.0:5000/dingtalk/callback 接收回调")
    
    # 发送启动消息
    send_to_dingtalk("✅ 钉钉交互式分析服务器已启动\n\n输入'帮助'查看可用指令")
    
    # 启动Flask服务器
    try:
        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\n服务器正在停止...")
        send_to_dingtalk("🛑 钉钉交互式分析服务器已停止")
    except Exception as e:
        print(f"服务器启动失败: {e}")
        send_to_dingtalk(f"❌ 服务器启动失败: {str(e)}")

if __name__ == "__main__":
    main()