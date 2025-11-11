"""
绘制噪声信息工具箱架构图
"""
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

def draw_architecture():
    fig, ax = plt.subplots(1, 1, figsize=(12, 10))
    
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 绘制各组件框
    components = [
        {
            'name': 'FastAPI Application',
            'pos': (0.5, 9),
            'width': 3,
            'height': 1,
            'color': '#FFB6C1',
            'text': 'FastAPI应用\n(main.py)'
        },
        {
            'name': 'AudioProcessingTaskManager',
            'pos': (0.5, 7.5),
            'width': 3,
            'height': 1,
            'color': '#87CEEB',
            'text': 'AudioProcessingTaskManager\n(background_tasks.py)'
        },
        {
            'name': 'AudioFileMonitor',
            'pos': (0.5, 6),
            'width': 3,
            'height': 1,
            'color': '#87CEEB',
            'text': 'AudioFileMonitor\n(file_monitor.py)'
        },
        {
            'name': 'AudioFileHandler',
            'pos': (0.5, 4.5),
            'width': 3,
            'height': 1,
            'color': '#87CEEB',
            'text': 'AudioFileHandler\n(file_monitor.py)'
        },
        {
            'name': 'Watchdog Observer',
            'pos': (0.5, 3),
            'width': 3,
            'height': 1,
            'color': '#DDA0DD',
            'text': 'Watchdog Observer\n(第三方库)'
        },
        {
            'name': 'FileSystem',
            'pos': (0.5, 1.5),
            'width': 3,
            'height': 1,
            'color': '#90EE90',
            'text': '文件系统\n(音频文件.wav/.tdms)'
        },
        {
            'name': 'AudioProcessor',
            'pos': (5, 7.5),
            'width': 3,
            'height': 1,
            'color': '#87CEEB',
            'text': 'AudioProcessor\n(audio_processor.py)'
        },
        {
            'name': 'TDMSConverter',
            'pos': (5, 6),
            'width': 3,
            'height': 1,
            'color': '#87CEEB',
            'text': 'TDMSConverter\n(tdms_converter.py)'
        },
        {
            'name': 'Callback Chain',
            'pos': (9, 7.5),
            'width': 3,
            'height': 1,
            'color': '#98FB98',
            'text': '回调链\n(set_processing_callback)'
        },
        {
            'name': 'WebSocket Clients',
            'pos': (9, 6),
            'width': 3,
            'height': 1,
            'color': '#FFD700',
            'text': 'WebSocket客户端\n(Streamlit前端)'
        }
    ]
    
    # 绘制组件框
    for comp in components:
        x, y = comp['pos']
        w, h = comp['width'], comp['height']
        rect = patches.Rectangle((x - w/2, y - h/2), w, h, 
                               linewidth=2, 
                               edgecolor='black', 
                               facecolor=comp['color'],
                               alpha=0.7)
        ax.add_patch(rect)
        
        # 添加文本
        ax.text(x, y, comp['text'], 
                ha='center', va='center', 
                fontsize=9, fontweight='bold')
    
    # 绘制箭头连接线
    arrows = [
        # 垂直方向箭头
        {'from': (0.5, 8.5), 'to': (0.5, 8)},
        {'from': (0.5, 7), 'to': (0.5, 6.5)},
        {'from': (0.5, 5.5), 'to': (0.5, 5)},
        {'from': (0.5, 4), 'to': (0.5, 3.5)},
        {'from': (0.5, 2.5), 'to': (0.5, 2)},
        
        # 横向箭头
        {'from': (2, 7.5), 'to': (3.5, 7.5)},  # TaskManager -> AudioProcessor
        {'from': (2, 6), 'to': (3.5, 6)},      # Monitor -> TDMSConverter
        
        # 右侧箭头
        {'from': (6.5, 7.5), 'to': (7.5, 7.5)},  # AudioProcessor -> Callback
        {'from': (8, 7), 'to': (8, 6.5)},         # Callback -> WebSocket
        
        # 文件系统到Handler的双向箭头
        {'from': (0.5, 2), 'to': (0.5, 2.5), 'style': '<->'},
    ]
    
    for arrow in arrows:
        start = arrow['from']
        end = arrow['to']
        style = arrow.get('style', '->')
        ax.annotate('', xy=end, xytext=start,
                   arrowprops=dict(arrowstyle=style, lw=1.5, color='black'))
    
    # 添加说明文字
    ax.text(8, 9, '噪声信息工具箱架构图', fontsize=16, fontweight='bold', ha='center')
    ax.text(8, 8.5, '展示了文件监控和处理的完整流程', fontsize=12, ha='center')
    
    # 设置坐标轴
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 10)
    ax.set_aspect('equal')
    ax.axis('off')
    
    plt.tight_layout()
    plt.savefig('architecture.png', dpi=300, bbox_inches='tight')
    plt.show()

if __name__ == "__main__":
    draw_architecture()