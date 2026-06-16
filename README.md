# XPOScope

## 项目结构说明

```cmd
├─dynamicExerciser  	  # 小程序自动化点击测试模块
│  ├─data				  # 运行数据存放位置
│  │ ├─page_text
│  │ ├─picCache
│  │ └─screenshots
│  └─page_utils
├─MiniAppLog           # 小程序流量和页面文本Log
├─OcrDump				  # 图片文本识别模块
├─trafficMonitor		  # 流量监听模块
├─replay               # 重放
├─strategy             # 交互策略
├─Configs              # 设定数值
├─stanford-corenlp-4.2.1  # 解压后的nlp工具
├─config.py				  # 全局配置文件
└─xpochecker_pc.py	  # 单个小程序测试启动器
```

## 项目构建说明

基于XPOScope工具https://github.com/ppflower/XPOScope.git构建
1. 修改地方：无需yolo训练数据，如预处理文件 ./dynamicExerciser/checkpoints 和 数据集
修改文件后缀为_pc。不需要。针对pc端微信小程序修改。

2. ./dynamicExerciser/data 运行时图片文本存放位置属于临时文件，使用者按照项目结构进行创建即可
3. ./MiniAppLog 小程序流量和页面文本Log属于临时文件，使用者进行创建即可


## 代码定制化说明

该项目所有小程序启动运行都是基于windows PC微信小程序

1. 小程序启动和运行

   - dynamicExerciser/mini_app_auto_pc.py 中start_mini_app(self)，只有微信小程序处理

   - 根据微信页面中的固定组件位置点击，搜索目标小程序，点击打开。参数可调整。

   - 通过DEVICE_WIDTH和DEVICE_HEIGHT可以确认窗口大小以及目标组件的大小是否正确。

     

2. 小程序测试和运行

   - MINI_APP_TEST_TIME : 单个小程序运行时间
   - TCP_PORT : 本地TCP数据传输会使用的端口，如果存在冲突进行修改（默认 12345）

   

## XPOScope使用说明

1. 设备准备操作

   - 使用抓包工具如mitmproxy，需要电脑配置手动代理如8080。
   - 在链接（链接：https://pan.baidu.com/s/1gXsLrqnFZT1jeAN9eOyKMA  提取码：7mha）中下载stanford-corenlp-4.1.2工具包.或者解压。

2. 交互策略模块
   - 调用大模型API需要修改模型、密钥key


3. 启动文本处理模块
   - 将stanford-corenlp-4.1.2工具包解压在PC设备上，并运行下述命令行

     ```
     java -mx4g -cp "*" edu.stanford.nlp.pipeline.StanfordCoreNLPServer -preload tokenize,ssplit,pos,lemma,ner,parse,depparse -status_port 9000 -port 9000 -timeout 15000
     ```

3. 启动XPOScope工具

   - xpochecker_pc.py:  仅运行单个小程序，修改mini_app_platform为1：微信、mini_app_name参数

   
