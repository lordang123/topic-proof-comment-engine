# 第三方组件

本仓库**不附带**下列任何软件或模型。安装脚本按各自官方渠道下载，许可证以各项目官方发布的为准。

| 组件 | 用途 | 怎么获得 | 许可证 |
|---|---|---|---|
| [mlx-whisper](https://github.com/ml-explore/mlx-examples) | Apple 芯片上的语音识别 | pip | MIT |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 其他电脑上的语音识别 | pip | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | faster-whisper 的推理库 | pip（随 faster-whisper） | MIT |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) | 下载模型 | pip | Apache-2.0 |
| [Whisper 模型权重](https://github.com/openai/whisper) | 语音识别模型（mlx-community、Systran 转换版） | 首次运行时从 Hugging Face 下载 | MIT |
| NVIDIA cuBLAS / cuDNN（pip 包） | Windows 上用显卡转录（可选） | pip | NVIDIA 软件许可 |
| [FFmpeg](https://ffmpeg.org) | 从视频里抽音轨 | Homebrew / winget | LGPL / GPL（取决于构建） |
| [ego lite](https://lite.ego.app/) | 在你自己的登录状态下读取网页 | 你自己按官方说明安装 | 以 ego lite 官方条款为准 |

本项目与抖音、字节跳动、ego lite 的开发方都没有关联。
