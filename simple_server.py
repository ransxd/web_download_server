#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的文件下载服务器
功能：
    - 提供Web界面浏览和下载文件
    - 支持文件夹折叠/展开
    - 支持文件夹打包下载（ZIP格式）
    - 可在后台运行，断开SSH也能继续服务

使用方法：

1. 后台运行（推荐）：
    nohup python3 simple_server.py > server.log 2>&1 &
    
2. 前台运行（调试用）：
    python3 simple_server.py

3. 停止服务器：
    kill $(cat simple_server.pid)
    或
    ps aux | grep simple_server.py  # 查看PID
    kill <PID>                      # 使用实际的PID替换<PID>

4. 查看日志：
    tail -f server.log

注意事项：
    - 默认端口为5299，可以修改 server_address 变量更改端口
    - 服务器默认使用当前目录作为下载目录
    - 隐藏文件（以.开头）不会显示在列表中
    - 建议使用方法1运行，这样断开SSH连接后服务器仍会继续运行
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
import signal
import sys
import zipfile
import io
import urllib.parse
import shutil
import tempfile

# 使用当前目录作为下载目录
DOWNLOAD_DIR = os.getcwd()
PID_FILE = "simple_server.pid"
TEMP_DIR = tempfile.gettempdir()  # 临时文件目录

def write_pid():
    """写入PID文件"""
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

def remove_pid():
    """删除PID文件"""
    try:
        os.remove(PID_FILE)
    except OSError:
        pass

def signal_handler(signum, frame):
    """处理退出信号"""
    print("\n正在关闭服务器...")
    remove_pid()
    sys.exit(0)

def create_zip_file(directory, base_path):
    """创建目录的ZIP文件"""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for root, dirs, files in os.walk(directory):
            for file in files:
                # 跳过隐藏文件、PID文件和日志文件
                if file.startswith('.') or file == PID_FILE or file == 'server.log':
                    continue
                file_path = os.path.join(root, file)
                # 使用相对于目标目录的路径作为ZIP中的路径
                arcname = os.path.relpath(file_path, directory)
                zip_file.write(file_path, arcname)
    zip_buffer.seek(0)
    return zip_buffer

def get_directory_structure(directory):
    """获取目录结构，区分文件和文件夹"""
    structure = {'files': [], 'dirs': {}}
    
    # 获取当前目录下的所有内容
    try:
        items = os.listdir(directory)
    except OSError:
        return structure

    for item in items:
        # 跳过隐藏文件、PID文件和日志文件
        if item.startswith('.') or item == PID_FILE or item == 'server.log':
            continue
            
        full_path = os.path.join(directory, item)
        rel_path = os.path.relpath(full_path, DOWNLOAD_DIR)
        
        if os.path.isfile(full_path):
            structure['files'].append(rel_path)
        elif os.path.isdir(full_path):
            structure['dirs'][rel_path] = get_directory_structure(full_path)
            
    return structure

class DownloadHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        print(f"使用目录: {DOWNLOAD_DIR}")
        super().__init__(*args, directory=DOWNLOAD_DIR, **kwargs)

    def do_GET(self):
        """处理GET请求"""
        # 检查是否是下载文件夹的请求
        if self.path.startswith('/download_folder/'):
            folder_path = urllib.parse.unquote(self.path[16:])
            self.send_folder_as_zip(folder_path)
            return
        super().do_GET()

    def send_folder_as_zip(self, folder_path):
        """将文件夹打包成ZIP发送"""
        try:
            # 解码URL编码的路径
            folder_path = urllib.parse.unquote(folder_path)
            # 规范化路径分隔符
            folder_path = folder_path.replace('/', os.sep).replace('\\', os.sep)
            
            # 确保路径安全
            full_path = os.path.join(DOWNLOAD_DIR, folder_path)
            full_path = os.path.normpath(full_path)
            
            print(f"请求下载目录: {full_path}")
            print(f"基准目录: {DOWNLOAD_DIR}")
            
            if not os.path.exists(full_path):
                print(f"文件夹不存在: {full_path}")
                self.send_error(404, "Folder not found")
                return

            if not os.path.isdir(full_path):
                print(f"不是文件夹: {full_path}")
                self.send_error(400, "Not a directory")
                return

            print(f"正在打包文件夹: {full_path}")
            # 创建ZIP文件
            zip_buffer = create_zip_file(full_path, full_path)
            
            # 准备文件名
            safe_filename = os.path.basename(folder_path)
            if not safe_filename:  # 如果是根目录，使用目录名
                safe_filename = os.path.basename(full_path)
            safe_filename = safe_filename.encode('utf-8').decode('utf-8', 'ignore')
            
            # 发送响应头
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Disposition', f'attachment; filename*=UTF-8\'\'{urllib.parse.quote(safe_filename)}.zip')
            self.send_header('Content-Length', str(zip_buffer.tell()))
            self.end_headers()
            
            # ���送ZIP文件内容
            shutil.copyfileobj(zip_buffer, self.wfile)
            zip_buffer.close()
            print(f"文件夹打包完成: {safe_filename}.zip")
            
        except Exception as e:
            print(f"打包文件夹出错: {str(e)}")
            self.send_error(500, "Internal server error")

    def list_directory(self, path):
        """生成简单的目录列表页面"""
        print(f"正在列出目录: {path}")
        try:
            # 获取目录结构
            structure = get_directory_structure(path)
            print(f"目录结构: {structure}")
        except OSError as e:
            print(f"列出目录失败: {str(e)}")
            self.send_error(404, "没有权限访问目录")
            return None
        
        # 发送响应头
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

        # 生成简单的HTML页面
        content = f"""
        <html>
        <head>
            <title>文件下载</title>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h2 {{ color: #333; }}
                ul {{ list-style: none; padding: 0; }}
                li {{ margin: 10px 0; }}
                .file-link {{ 
                    text-decoration: none;
                    color: #0066cc;
                    padding: 5px 10px;
                    border: 1px solid #0066cc;
                    border-radius: 3px;
                    display: inline-block;
                }}
                .file-link:hover {{ background-color: #0066cc; color: white; }}
                .folder {{ 
                    cursor: pointer;
                    color: #333;
                    padding: 5px 10px;
                    background-color: #f0f0f0;
                    border-radius: 3px;
                    display: inline-block;
                }}
                .folder:hover {{ background-color: #e0e0e0; }}
                .folder-content {{ display: none; margin-left: 20px; }}
                .empty {{ color: #666; }}
                .download-zip {{
                    text-decoration: none;
                    color: #28a745;
                    padding: 3px 8px;
                    border: 1px solid #28a745;
                    border-radius: 3px;
                    margin-left: 10px;
                    font-size: 0.9em;
                }}
                .download-zip:hover {{
                    background-color: #28a745;
                    color: white;
                }}
            </style>
            <script>
                function toggleFolder(folderId) {{
                    const content = document.getElementById(folderId);
                    const folderIcon = document.getElementById('icon_' + folderId);
                    if (content.style.display === 'none') {{
                        content.style.display = 'block';
                        folderIcon.textContent = '[-]';
                    }} else {{
                        content.style.display = 'none';
                        folderIcon.textContent = '[+]';
                    }}
                }}
            </script>
        </head>
        <body>
            <h2>文件下载服务器</h2>
            <p style="color: #666;">当前目录: {DOWNLOAD_DIR}</p>
        """
        
        def render_structure(struct, parent_id='root'):
            html = "<ul>"
            # 先显示文件
            for file_path in sorted(struct['files']):
                display_name = os.path.basename(file_path)
                encoded_path = urllib.parse.quote(file_path)
                html += f'<li><a class="file-link" href="{encoded_path}">{display_name}</a></li>\n'
            
            # 再显示文件夹
            for dir_path in sorted(struct['dirs'].keys()):
                dir_name = os.path.basename(dir_path)
                folder_id = f"folder_{dir_path.replace(os.sep, '_')}"
                encoded_path = urllib.parse.quote(dir_path)
                html += f'''
                    <li>
                        <div class="folder" onclick="toggleFolder('{folder_id}')">
                            <span id="icon_{folder_id}">[+]</span> {dir_name}
                            <a href="/download_folder/{encoded_path}" class="download-zip" onclick="event.stopPropagation()">下载ZIP</a>
                        </div>
                        <div id="{folder_id}" class="folder-content">
                            {render_structure(struct['dirs'][dir_path], folder_id)}
                        </div>
                    </li>
                '''
            html += "</ul>"
            return html

        if structure['files'] or structure['dirs']:
            content += render_structure(structure)
        else:
            content += '<p class="empty">当前目录为空</p>'
        
        content += """
        </body>
        </html>
        """
        
        # 发送内容
        self.wfile.write(content.encode('utf-8'))
        return None

if __name__ == '__main__':
    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 写入PID文件
    write_pid()
    
    try:
        # 启动服务器
        server_address = ('', 5299)
        httpd = HTTPServer(server_address, DownloadHandler)
        print(f"服务器运行在 http://0.0.0.0:5299/")
        print(f"服务的目录是: {DOWNLOAD_DIR}")
        print(f"PID: {os.getpid()}")
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭服务器...")
    finally:
        remove_pid()