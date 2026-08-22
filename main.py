import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import markdown
import os
import shutil
from pathlib import Path
import json
import webbrowser
import datetime
import sys
import re

def setup_dpi_awareness():
    """设置高DPI支持，不会创建额外窗口"""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except:
                pass
        return True
    except:
        return False

setup_dpi_awareness()

class MarkdownToHTMLApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Markdown 转 HTML 工具")
        
        self.setup_window_size()
        self.setup_fonts()
        
        self.style = ttk.Style()
        try:
            self.style.theme_use('vista')
        except:
            pass
        
        # 变量
        self.input_file = tk.StringVar()
        self.output_dir = tk.StringVar(value=os.path.expanduser("~/Documents"))
        self.css_file = tk.StringVar()
        self.auto_open = tk.BooleanVar(value=True)
        self.embed_svg = tk.BooleanVar(value=True)  # 是否嵌入SVG
        
        # 创建界面
        self.create_menu()
        self.create_widgets()
        self.create_statusbar()
        
        self.load_config()
        self.setup_drag_drop()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def setup_window_size(self):
        """根据DPI设置窗口大小"""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            dc = user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)
            scale = dpi / 96.0
            
            if scale >= 2.0:
                self.root.geometry("1100x800")
                self.root.minsize(1000, 700)
                self.root.tk.call('tk', 'scaling', 1.5)
            elif scale >= 1.5:
                self.root.geometry("1000x750")
                self.root.minsize(900, 650)
                self.root.tk.call('tk', 'scaling', 1.25)
            elif scale >= 1.25:
                self.root.geometry("950x700")
                self.root.minsize(850, 600)
                self.root.tk.call('tk', 'scaling', 1.1)
            else:
                self.root.geometry("900x700")
                self.root.minsize(800, 600)
                self.root.tk.call('tk', 'scaling', 1.0)
        except:
            self.root.geometry("900x700")
            self.root.minsize(800, 600)
    
    def setup_fonts(self):
        """设置字体"""
        try:
            default_font = ('Microsoft YaHei', 9)
            self.root.option_add('*Font', default_font)
            
            style = ttk.Style()
            style.configure('.', font=default_font)
            style.configure('TLabel', font=default_font)
            style.configure('TButton', font=default_font)
            style.configure('TEntry', font=default_font)
            style.configure('TLabelframe.Label', font=('Microsoft YaHei', 9, 'bold'))
        except:
            pass
    
    def create_menu(self):
        """创建菜单栏"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="选择Markdown文件", command=self.select_input_file)
        file_menu.add_command(label="选择CSS文件", command=self.select_css_file)
        file_menu.add_separator()
        file_menu.add_command(label="转换", command=self.convert_markdown)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.on_closing)
        
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="设置", menu=settings_menu)
        settings_menu.add_command(label="设置输出目录", command=self.select_output_dir)
        settings_menu.add_separator()
        settings_menu.add_checkbutton(label="转换后自动打开HTML", variable=self.auto_open)
        settings_menu.add_checkbutton(label="自动嵌入SVG图片", variable=self.embed_svg)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="使用说明", command=self.show_help)
        help_menu.add_command(label="关于", command=self.show_about)
        
        self.root.bind('<Control-o>', lambda e: self.select_input_file())
        self.root.bind('<Control-Return>', lambda e: self.convert_markdown())
        self.root.bind('<Control-q>', lambda e: self.on_closing())
    
    def create_widgets(self):
        """创建主界面组件"""
        main_frame = ttk.Frame(self.root, padding="12")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        title_frame = ttk.Frame(main_frame)
        title_frame.pack(fill=tk.X, pady=(0, 12))
        
        title = ttk.Label(
            title_frame,
            text="📄 你就转吧，一转一个不吱声",
            font=('Microsoft YaHei', 18, 'bold')
        )
        title.pack(side=tk.LEFT)
        
        version = ttk.Label(
            title_frame,
            text="v1.2",
            font=('Microsoft YaHei', 9),
            foreground='gray'
        )
        version.pack(side=tk.LEFT, padx=(8, 0))
        
        file_frame = ttk.LabelFrame(main_frame, text="📁 文件选择", padding="12")
        file_frame.pack(fill=tk.X, pady=(0, 10))
        
        input_frame = ttk.Frame(file_frame)
        input_frame.pack(fill=tk.X, pady=4)
        
        ttk.Label(input_frame, text="Markdown文件:").pack(side=tk.LEFT)
        input_entry = ttk.Entry(input_frame, textvariable=self.input_file)
        input_entry.pack(side=tk.LEFT, padx=(10, 10), fill=tk.X, expand=True)
        
        ttk.Button(
            input_frame, 
            text="📂 选择文件", 
            command=self.select_input_file,
            width=12
        ).pack(side=tk.RIGHT, padx=(0, 4))
        
        css_frame = ttk.Frame(file_frame)
        css_frame.pack(fill=tk.X, pady=4)
        
        ttk.Label(css_frame, text="CSS样式文件:").pack(side=tk.LEFT)
        css_entry = ttk.Entry(css_frame, textvariable=self.css_file)
        css_entry.pack(side=tk.LEFT, padx=(10, 10), fill=tk.X, expand=True)
        
        ttk.Button(
            css_frame,
            text="📂 选择CSS",
            command=self.select_css_file,
            width=12
        ).pack(side=tk.RIGHT, padx=(0, 4))
        
        drop_label = ttk.Label(
            file_frame,
            text="💡 提示：可以直接拖拽Markdown文件到窗口",
            font=('Microsoft YaHei', 9, 'italic'),
            foreground='#666'
        )
        drop_label.pack(pady=(6, 0))
        
        output_frame = ttk.LabelFrame(main_frame, text="📤 输出设置", padding="12")
        output_frame.pack(fill=tk.X, pady=(0, 10))
        
        output_dir_frame = ttk.Frame(output_frame)
        output_dir_frame.pack(fill=tk.X, pady=4)
        
        ttk.Label(output_dir_frame, text="输出目录:").pack(side=tk.LEFT)
        output_entry = ttk.Entry(output_dir_frame, textvariable=self.output_dir)
        output_entry.pack(side=tk.LEFT, padx=(10, 10), fill=tk.X, expand=True)
        
        ttk.Button(
            output_dir_frame,
            text="📂 选择目录",
            command=self.select_output_dir,
            width=12
        ).pack(side=tk.RIGHT)
        
        options_frame = ttk.Frame(output_frame)
        options_frame.pack(fill=tk.X, pady=(8, 0))
        
        ttk.Checkbutton(
            options_frame,
            text="转换后自动打开HTML",
            variable=self.auto_open
        ).pack(side=tk.LEFT, padx=(0, 20))
        
        ttk.Checkbutton(
            options_frame,
            text="自动嵌入SVG图片（将.svg内容直接插入HTML）",
            variable=self.embed_svg
        ).pack(side=tk.LEFT, padx=(0, 20))
        
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=10)
        
        ttk.Button(
            btn_frame,
            text="🔄 转换 (Ctrl+Enter)",
            command=self.convert_markdown,
            width=22
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            btn_frame,
            text="🗑️ 清空",
            command=self.clear_all,
            width=18
        ).pack(side=tk.LEFT, padx=5)
        
        log_frame = ttk.LabelFrame(main_frame, text="📝 日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.pack(fill=tk.X, pady=(0, 6))
        
        ttk.Button(
            log_toolbar,
            text="清空日志",
            command=self.clear_log,
            width=12
        ).pack(side=tk.LEFT)
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=10,
            font=('Consolas', 10),
            wrap=tk.WORD,
            bg='#f8f9fa',
            fg='#1a1a1a'
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        self.log_text.tag_config('success', foreground='#28a745')
        self.log_text.tag_config('error', foreground='#dc3545')
        self.log_text.tag_config('info', foreground='#007bff')
        self.log_text.tag_config('warning', foreground='#ffc107')
        
        self.log("🚀 程序已启动，请选择Markdown文件", 'info')
        self.log("💡 支持拖拽文件到窗口", 'info')
        self.log("🧪 支持 mhchem 化学方程式 (\\ce{})", 'info')
        self.log("📊 支持自动嵌入 SVG 图片", 'info')
    
    def clear_log(self):
        """清空日志"""
        self.log_text.delete(1.0, tk.END)
        self.log("🗑️ 日志已清空", 'info')
    
    def create_statusbar(self):
        """创建状态栏"""
        self.statusbar = ttk.Label(
            self.root,
            text="就绪",
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(6, 2)
        )
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)
    
    def setup_drag_drop(self):
        """设置拖拽功能"""
        try:
            from tkinterdnd2 import DND_FILES
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self.on_drop)
            self.log("✅ 拖拽功能已启用", 'success')
        except:
            self.log("⚠️ 拖拽功能不可用，请使用按钮选择文件", 'warning')
            self.log("💡 安装 tkinterdnd2: pip install tkinterdnd2", 'info')
    
    def on_drop(self, event):
        """处理拖拽文件"""
        try:
            files = self.root.tk.splitlist(event.data)
            if files:
                file_path = files[0]
                file_path = file_path.strip('{}').strip()
                
                if file_path.lower().endswith(('.md', '.markdown', '.txt')):
                    self.input_file.set(file_path)
                    self.log(f"📥 已拖入文件: {os.path.basename(file_path)}", 'success')
                    self.statusbar.config(text=f"已选择: {os.path.basename(file_path)}")
                    
                    file_dir = os.path.dirname(file_path)
                    if os.path.exists(file_dir):
                        self.output_dir.set(file_dir)
                else:
                    self.log(f"⚠️ 不支持的文件类型: {os.path.basename(file_path)}", 'warning')
                    messagebox.showwarning("不支持", "请拖入Markdown文件 (.md, .markdown, .txt)")
        except Exception as e:
            self.log(f"❌ 拖拽处理错误: {str(e)}", 'error')
    
    def select_input_file(self):
        """选择输入文件"""
        file_path = filedialog.askopenfilename(
            title="选择Markdown文件",
            filetypes=[
                ("Markdown文件", "*.md *.markdown *.txt"),
                ("所有文件", "*.*")
            ]
        )
        if file_path:
            self.input_file.set(file_path)
            self.log(f"📂 已选择文件: {os.path.basename(file_path)}", 'success')
            self.statusbar.config(text=f"已选择: {os.path.basename(file_path)}")
            
            file_dir = os.path.dirname(file_path)
            if os.path.exists(file_dir):
                self.output_dir.set(file_dir)
    
    def select_css_file(self):
        """选择CSS文件"""
        file_path = filedialog.askopenfilename(
            title="选择CSS样式文件",
            filetypes=[
                ("CSS文件", "*.css"),
                ("所有文件", "*.*")
            ]
        )
        if file_path:
            self.css_file.set(file_path)
            self.log(f"🎨 已选择CSS: {os.path.basename(file_path)}", 'success')
    
    def select_output_dir(self):
        """选择输出目录"""
        dir_path = filedialog.askdirectory(
            title="选择输出目录",
            initialdir=self.output_dir.get()
        )
        if dir_path:
            self.output_dir.set(dir_path)
            self.log(f"📁 输出目录已设置: {dir_path}", 'info')
    
    def load_config(self):
        """加载配置"""
        config_file = "markdown_converter_config.json"
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.output_dir.set(config.get('output_dir', self.output_dir.get()))
                    self.auto_open.set(config.get('auto_open', True))
                    self.css_file.set(config.get('css_file', ''))
                    self.embed_svg.set(config.get('embed_svg', True))
            except:
                pass
    
    def save_config(self):
        """保存配置"""
        config = {
            'output_dir': self.output_dir.get(),
            'auto_open': self.auto_open.get(),
            'css_file': self.css_file.get(),
            'embed_svg': self.embed_svg.get()
        }
        try:
            with open('markdown_converter_config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def log(self, message, level='info'):
        """添加日志"""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] {message}\n"
        
        self.log_text.insert(tk.END, formatted_msg, level)
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def clear_all(self):
        """清空所有"""
        self.input_file.set("")
        self.css_file.set("")
        self.log_text.delete(1.0, tk.END)
        self.log("🗑️ 已清空所有", 'info')
        self.statusbar.config(text="就绪")
    
    def on_closing(self):
        """窗口关闭事件"""
        self.save_config()
        self.root.destroy()
    
    def preprocess_latex(self, content):
        """预处理LaTeX公式，保护$$不被转义"""
        def protect_display_math(match):
            formula = match.group(1)
            return f'<div class="katex-display-protected">$${formula}$$</div>'
        
        def protect_inline_math(match):
            formula = match.group(1)
            return f'<span class="katex-inline-protected">${formula}$</span>'
        
        content = re.sub(r'\$\$([^\$]+)\$\$', protect_display_math, content, flags=re.DOTALL)
        content = re.sub(r'(?<!\$)\$([^$]+)\$(?!\$)', protect_inline_math, content)
        
        return content
    
    def postprocess_html(self, html_content):
        """后处理HTML，恢复LaTeX公式"""
        html_content = re.sub(
            r'<div class="katex-display-protected">\$\$([^\$]+)\$\$</div>',
            r'$$\1$$',
            html_content
        )
        
        html_content = re.sub(
            r'<span class="katex-inline-protected">\$([^\$]+)\$</span>',
            r'$\1$',
            html_content
        )
        
        return html_content
    
    def embed_svg_images(self, html_content, md_file_path, output_dir):
        """将HTML中的SVG引用替换为内联SVG代码"""
        if not self.embed_svg.get():
            return html_content
        
        md_dir = os.path.dirname(md_file_path) if md_file_path else output_dir
        
        def process_img_tag(match):
            full_tag = match.group(0)
            
            # 提取 alt 和 src
            alt = ""
            src = ""
            
            alt_match = re.search(r'alt="([^"]*)"', full_tag)
            if alt_match:
                alt = alt_match.group(1)
            
            src_match = re.search(r'src="([^"]+)"', full_tag)
            if not src_match:
                return full_tag
            src = src_match.group(1)
            
            # 只处理 SVG
            if not src.lower().endswith('.svg'):
                return full_tag
            
            # 查找 SVG 文件
            svg_path = src
            if not os.path.isabs(svg_path):
                svg_path = os.path.join(md_dir, src)
            
            if not os.path.exists(svg_path):
                svg_path = os.path.join(output_dir, src)
            
            if not os.path.exists(svg_path):
                self.log(f"⚠️ SVG文件不存在: {src}", 'warning')
                return full_tag
            
            try:
                with open(svg_path, 'r', encoding='utf-8') as f:
                    svg_content = f.read()
                
                # 清理 SVG 内容：移除 XML 声明和 DOCTYPE
                svg_content = re.sub(r'<\?xml[^?]*\?>', '', svg_content)
                svg_content = re.sub(r'<!DOCTYPE[^>]*>', '', svg_content)
                svg_content = re.sub(r'\n\s*\n', '\n', svg_content)  # 去除多余空行
                svg_content = svg_content.strip()
                
                # 如果 alt 为空，使用文件名
                if not alt:
                    alt = os.path.splitext(os.path.basename(src))[0]
                
                # 构建 figure
                result = f'<figure class="svg-figure">\n'
                result += f'  {svg_content}\n'
                result += f'  <figcaption>{alt}</figcaption>\n'
                result += f'</figure>'
                
                self.log(f"📊 已嵌入SVG: {os.path.basename(src)}", 'success')
                return result
                
            except Exception as e:
                self.log(f"❌ 嵌入SVG失败 {src}: {str(e)}", 'error')
                return full_tag
        
        # 匹配所有 img 标签
        pattern = r'<img\s+[^>]+>'
        html_content = re.sub(pattern, process_img_tag, html_content, flags=re.IGNORECASE)
        
        return html_content
    
    def convert_markdown(self):
        """转换Markdown到HTML"""
        input_path = self.input_file.get()
        if not input_path:
            messagebox.showwarning("警告", "请先选择一个Markdown文件")
            return
        
        if not os.path.exists(input_path):
            messagebox.showerror("错误", "文件不存在")
            return
        
        try:
            self.statusbar.config(text="正在转换...")
            self.root.update()
            
            # 读取Markdown文件
            with open(input_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
            
            self.log("📖 读取Markdown文件成功", 'success')
            
            # 预处理：保护 --- 不被解析为标题
            lines = md_content.split('\n')
            in_code_block = False
            new_lines = []
            
            for line in lines:
                if line.strip().startswith('```') or line.strip().startswith('~~~'):
                    in_code_block = not in_code_block
                    new_lines.append(line)
                    continue
                
                if in_code_block:
                    new_lines.append(line)
                    continue
                
                if re.match(r'^\s*---\s*$', line):
                    new_lines.append('<!-- HR_PLACEHOLDER -->')
                else:
                    new_lines.append(line)
            
            md_content = '\n'.join(new_lines)
            
            # 预处理：保护LaTeX公式
            md_content = self.preprocess_latex(md_content)
            
            # 转换Markdown到HTML
            html_content = markdown.markdown(
                md_content,
                extensions=[
                    'extra',
                    'codehilite',
                    'toc',
                    'tables',
                    'fenced_code',
                    'footnotes',
                    'nl2br'
                ]
            )
            
            # 后处理：将占位符替换为 <hr />
            html_content = html_content.replace('<!-- HR_PLACEHOLDER -->', '<hr />')
            
            html_content = re.sub(
                r'<h2 id="[^"]*">---</h2>',
                '<hr />',
                html_content
            )
            
            # 后处理：恢复LaTeX公式
            html_content = self.postprocess_html(html_content)
            
            # 嵌入SVG图片
            output_dir = self.output_dir.get()
            html_content = self.embed_svg_images(html_content, input_path, output_dir)
            
            self.log("🔄 Markdown转换完成", 'success')
            
            # 读取CSS
            css_content = self.get_css_content()
            
            # 构建完整的HTML
            output_html = self.build_html(html_content, css_content)
            
            # 生成输出文件名
            input_name = Path(input_path).stem
            output_name = f"{input_name}.html"
            output_path = os.path.join(output_dir, output_name)
            
            # 确保输出目录存在
            os.makedirs(output_dir, exist_ok=True)
            
            # 保存HTML文件
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(output_html)
            
            self.log(f"✅ HTML已保存: {output_path}", 'success')
            self.statusbar.config(text=f"转换完成: {output_name}")
            
            # 自动打开
            if self.auto_open.get():
                webbrowser.open(output_path)
                self.log("🌐 已在浏览器中打开", 'info')
            
            self.save_config()
            
            messagebox.showinfo("✅ 成功", f"转换完成！\n\n文件保存在:\n{output_path}")
            
        except Exception as e:
            error_msg = f"❌ 转换失败: {str(e)}"
            self.log(error_msg, 'error')
            self.statusbar.config(text="转换失败")
            messagebox.showerror("错误", error_msg)
    
    def get_css_content(self):
        """获取CSS内容"""
        css_content = ""
        
        if self.css_file.get() and os.path.exists(self.css_file.get()):
            try:
                with open(self.css_file.get(), 'r', encoding='utf-8') as f:
                    css_content = f.read()
                self.log("📝 使用自定义CSS文件", 'info')
            except:
                self.log("⚠️ 读取CSS文件失败，使用默认样式", 'warning')
        
        if not css_content:
            css_content = """
body {
    max-width: 900px;
    margin: 40px auto;
    padding: 0 20px;
    font-family: "Times New Roman", serif;
    line-height: 1.6;
    color: #333;
}
h1, h2, h3 { color: #1a1a1a; }
code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }
pre { background: #f6f8fa; padding: 16px; border-radius: 4px; overflow: auto; }
blockquote { border-left: 4px solid #ccc; padding-left: 16px; color: #666; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ddd; padding: 8px; }
th { background: #f6f8fa; }
img { max-width: 100%; }
.katex-display { overflow-x: auto; margin: 16px 0; }
.katex-display {
    position: relative;
    padding-right: 60px;
}
.tag-box {
    position: absolute;
    right: 10px;
    top: 50%;
    transform: translateY(-50%);
    background: #f8f8f8;
    border: 1px solid #ddd;
    padding: 4px 12px;
    border-radius: 4px;
    font-size: 0.8em;
    color: #555;
}
/* SVG 图片样式 */
.svg-figure {
    margin: 16px 0;
    text-align: center;
}
.svg-figure svg {
    max-width: 100%;
    height: auto;
}
.svg-figure figcaption {
    margin-top: 8px;
    font-size: 0.9em;
    color: #666;
    font-style: italic;
}
            """
            self.log("📝 使用内置默认样式", 'info')
        
        return css_content
    
    def build_html(self, content, css_content):
        """构建完整的HTML，支持 mhchem 化学方程式"""
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Markdown 转换结果</title>
    
    <!-- KaTeX 数学公式支持 -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
    
    <!-- mhchem 化学方程式支持 -->
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/mhchem.min.js"></script>
    
    <style>
        {css_content}
    </style>
</head>
<body>
    <div class="markdown-body">
        {content}
    </div>
    
    <script>
        document.addEventListener("DOMContentLoaded", function() {{
            if (typeof renderMathInElement === 'function') {{
                renderMathInElement(document.body, {{
                    delimiters: [
                        {{ left: '$$', right: '$$', display: true }},
                        {{ left: '$', right: '$', display: false }},
                        {{ left: '\\(', right: '\\)', display: false }},
                        {{ left: '\\[', right: '\\]', display: true }}
                    ],
                    throwOnError: false,
                    trust: true
                }});
            }}
            
            // 处理公式编号
            setTimeout(function() {{
                const displays = document.querySelectorAll('.katex-display');
                displays.forEach(function(display) {{
                    if (display.querySelector('.tag-box')) return;
                    const tagElement = display.querySelector('.katex .tag');
                    if (tagElement) {{
                        const tagBox = document.createElement('span');
                        tagBox.className = 'tag-box';
                        tagBox.textContent = tagElement.textContent.trim();
                        display.appendChild(tagBox);
                        tagElement.style.display = 'none';
                    }}
                }});
            }}, 200);
        }});
    </script>
</body>
</html>"""
    
    def show_help(self):
        """显示帮助"""
        help_text = """
📖 使用说明

📁 选择文件
   • 点击"选择文件"按钮
   • 或直接将文件拖拽到窗口
   • 支持 .md, .markdown, .txt

🎨 CSS样式
   • 可选：点击"选择CSS"使用自定义样式
   • 默认使用内置样式

📤 输出设置
   • 点击"选择目录"设置保存位置
   • 默认保存在源文件目录
   • 勾选"自动嵌入SVG"将SVG内容直接插入HTML

⌨️ 快捷键
   • Ctrl+O: 选择文件
   • Ctrl+Enter: 转换
   • Ctrl+Q: 退出

✨ 支持功能
   • 标准Markdown语法
   • LaTeX数学公式 ($...$, $$...$$)
   • 化学方程式 (\\ce{...})
   • 表格、代码高亮
   • 公式自动编号
   • 拖拽文件
   • SVG图片自动嵌入

🧪 化学方程式示例：
   $\\ce{H2O}$ - 水
   $\\ce{2H2 + O2 -> 2H2O}$ - 反应
   $\\ce{N2 + 3H2 <=> 2NH3}$ - 可逆反应
        """
        messagebox.showinfo("使用说明", help_text)
    
    def show_about(self):
        """显示关于"""
        about_text = """
📄 Markdown 转 HTML 工具

版本: 1.2
作者: Yore.ASH

✨ 功能特点:
• 支持拖拽文件
• LaTeX公式渲染 (KaTeX)
• 化学方程式支持 (mhchem)
• 自定义CSS样式
• 公式自动编号
• 自动打开HTML
• SVG图片自动嵌入

🔧 技术栈:
• Python 3
• Tkinter
• Markdown
• KaTeX
• mhchem

📧 联系: 2519711819@qq.com
🤝 合作: DeepSeek

© 2026
        """
        messagebox.showinfo("关于", about_text)


def main():
    """主函数"""
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
        root.withdraw()
        root.deiconify()
    except ImportError:
        print("⚠️ 未安装tkinterdnd2，拖拽功能不可用")
        print("💡 安装命令: pip install tkinterdnd2")
        root = tk.Tk()
    
    app = MarkdownToHTMLApp(root)
    root.lift()
    root.focus_force()
    root.mainloop()


if __name__ == "__main__":
    main()