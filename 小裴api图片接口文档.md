# 图片模型接口文档（api.aicopy.top 中转）

本文档根据当前应用的图片生成、应急生图和多模态编辑调用逻辑整理。中转地址固定使用：

```text
https://api.aicopy.top
```

为了安全，文档不写入明文密钥。调用时将你提供的密钥放到环境变量或服务端配置中，并统一按下面方式鉴权：

```http
Authorization: Bearer <API_KEY>
```

## 1. 通用规则

### 1.1 Base URL

应用里用户可填写 `https://api.aicopy.top`，后端在调用图片接口时会自动补 `/v1`。因此外部直接调用时推荐使用：

```text
https://api.aicopy.top/v1
```

### 1.2 通用请求头

```http
Content-Type: application/json
Accept: application/json
Authorization: Bearer <API_KEY>
User-Agent: Mozilla/5.0 AIGC-Workbench/1.0
```

### 1.3 超时时间

图片生成建议超时 `600` 秒。应用设置页默认也是 `600` 秒；遇到上游繁忙类错误时，应用后端会最多重试 3 次。

### 1.4 图片返回值兼容格式

当前应用会递归解析以下字段或文本格式作为生成图片：

```text
url
image_url
b64_json
result
image_b64
text / content / output_text 中的 Markdown 图片、http(s) 图片地址、data:image base64、/v1/... 相对地址
```

如果返回纯 base64，应用会补成：

```text
data:image/png;base64,<base64>
```

## 2. 查询模型列表

用于设置页“保存并加载模型”，图片页会使用加载到本地缓存的模型 ID。

```http
GET https://api.aicopy.top/v1/models
Authorization: Bearer <API_KEY>
Accept: application/json
```

示例响应：

```json
{
  "object": "list",
  "data": [
    {
      "id": "firefly-nano-banana-1k-1x1",
      "object": "model",
      "owned_by": "aicopy"
    }
  ]
}
```

应用只依赖 `data[].id`，`object` 和 `owned_by` 会透传展示。

## 3. 标准图片生成接口

大多数图片模型按 OpenAI 兼容格式走 `/images/generations`。

```http
POST https://api.aicopy.top/v1/images/generations
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

### 3.1 文生图请求

```json
{
  "model": "firefly-nano-banana-1k-1x1",
  "prompt": "一张干净的电商主图，白底，玻璃水杯，柔和棚拍光，高级质感",
  "n": 1,
  "size": "1024x1024"
}
```

说明：

- `model`：模型 ID。来自 `/v1/models` 或本文后面的内置映射。
- `prompt`：图片提示词，必填。
- `n`：当前应用每个任务固定请求 `1` 张；前端“并发数量”是同时提交多个任务。
- `size`：当模型 ID 没有自带尺寸信息时才建议传。若模型 ID 已包含 `1k`、`2k`、`4k`、`1024x1024` 等尺寸，应用会优先以模型名为准。

### 3.2 返回示例

URL 返回：

```json
{
  "data": [
    {
      "url": "https://api.aicopy.top/v1/files/xxx.png"
    }
  ]
}
```

Base64 返回：

```json
{
  "data": [
    {
      "b64_json": "iVBORw0KGgoAAA..."
    }
  ]
}
```

应用会尽量把图片下载到本地 `outputs/images`，因为生成链接可能有时效性。

## 4. 参考图 / 图生图

当前应用支持上传多张参考图，前端最多 7 张，每张最大 10MB。上传后会压缩成 JPEG，最长边不超过 1024，质量 85，并转成：

```text
data:image/jpeg;base64,<base64>
```

不同通道使用的参考图格式不同。

### 4.1 `/images/generations` 单图参考

部分 Grok 风格通道会把第一张参考图放到 `image` 字段，并移除 `data:image/...;base64,` 前缀：

```json
{
  "model": "grok-imagine-1.0-edit",
  "prompt": "保持人物一致，换成赛博朋克夜景风格",
  "n": 1,
  "size": "1024x1024",
  "image": "<纯base64>"
}
```

### 4.2 `/responses` 多图参考

GPT 本地版和多模态编辑优先走 `/responses`，参考图使用 `input_image`：

```json
{
  "model": "GPT本地版",
  "input": [
    {
      "role": "user",
      "content": [
        {
          "type": "input_image",
          "image_url": "data:image/jpeg;base64,<base64>"
        },
        {
          "type": "input_text",
          "text": "参考这张图，生成 1:1 的高级电商海报"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "image_generation",
      "size": "1024x1024"
    }
  ],
  "tool_choice": {
    "type": "image_generation"
  }
}
```

## 5. GPT 本地版 / 应急通道

应急生图页固定使用一组模型名。后端识别所有以 `GPT本地版` 开头的模型为本地 GPT 图片通道，并优先调用：

```http
POST https://api.aicopy.top/v1/responses
```

失败后会降级到：

```http
POST https://api.aicopy.top/v1/images/generations
```

降级请求示例：

```json
{
  "model": "GPT本地版",
  "prompt": "生成一张 16:9 科技发布会主视觉，深色背景，产品轮廓发光",
  "size": "1536x864",
  "n": 1,
  "response_format": "b64_json"
}
```

应急模型列表：

```text
GPT本地版
GPT本地版1k
GPT本地版2k
GPT本地版4k
GPT本地版-通道1
GPT本地版1k-通道1
GPT本地版2k-通道1
GPT本地版4k-通道1
GPT本地版-通道2
GPT本地版1k-通道2
GPT本地版2k-通道2
GPT本地版4k-通道2
GPT本地版-通道3
GPT本地版1k-通道3
GPT本地版2k-通道3
GPT本地版4k-通道3
gpt-image-2应急通道
gpt-image-2应急通道01
gpt-image-2应急通道02
gpt-image-2应急通道03
gpt-image-2应急通道04
gpt-image-2应急通道05
gpt-image-2应急通道06
```

注意：只有 `GPT本地版...` 会触发应用里的 `/responses` 优先逻辑；其他应急模型会按普通模型 ID 处理。

## 6. 多模态聊天 / 图片编辑兜底

对于部分 OpenAI 风格模型，应用会通过 `/chat/completions` 发送多图和提示词，并从流式文本中提取图片链接。

```http
POST https://api.aicopy.top/v1/chat/completions
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

请求示例：

```json
{
  "model": "firefly-nano-banana-1k-1x1",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "image_url",
          "image_url": {
            "url": "data:image/jpeg;base64,<base64>"
          }
        },
        {
          "type": "text",
          "text": "参考图片姿态，生成白底商品展示图"
        }
      ]
    }
  ],
  "stream": true
}
```

流式响应中，应用会读取 `choices[0].delta.content`，并匹配 Markdown 图片、URL 或 `/v1/...` 相对路径。

## 7. 模型 ID 规则

### 7.1 直接加载的远程模型

设置页从 `/v1/models` 加载到的模型 ID，会在图片页作为 `model` 直接传给后端。后端再按模型名判断是否需要补 `size`。

如果模型名包含以下模式，应用认为模型名自带尺寸，生成时不额外传 `size`：

```text
1k / 2k / 4k
1024x1024 / 1536x864 等像素尺寸
1k-1024x1024 这类组合
```

### 7.2 内置家族映射

后端保留了几个内置家族映射：

| 前端基础模型 | 实际 model ID 规则 | 示例 |
| --- | --- | --- |
| `firefly-nano-banana` | `firefly-nano-banana-{resolution}-{aspect}` | `firefly-nano-banana-1k-1x1` |
| `firefly-nano-banana-pro` | `firefly-nano-banana-pro-{resolution}-{aspect}` | `firefly-nano-banana-pro-2k-16x9` |
| `firefly-nano-banana2` | `firefly-nano-banana2-{resolution}-{aspect}` | `firefly-nano-banana2-4k-9x16` |
| `gpt-image-1` | `firefly-gpt-image-{resolution}-{aspect}` | `firefly-gpt-image-1k-1x1` |
| `grok-imagine-1.0` | 默认 `grok-imagine-1.0`，编辑变体 `grok-imagine-1.0-edit` | `grok-imagine-1.0-edit` |

## 8. 官方尺寸表

应用会把宽高比和清晰度档位转换成标准像素尺寸。

| 档位 | 1:1 | 16:9 | 9:16 | 4:3 | 3:4 | 3:2 | 2:3 | 4:5 | 5:4 | 21:9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1k | 1024x1024 | 1536x864 | 864x1536 | 1365x1024 | 1024x1365 | 1536x1024 | 1024x1536 | 1024x1280 | 1280x1024 | 1792x768 |
| 2k | 2048x2048 | 3072x1728 | 1728x3072 | 2730x2048 | 2048x2730 | 3072x2048 | 2048x3072 | 2048x2560 | 2560x2048 | 3584x1536 |
| 4k | 3840x3840 | 3840x2160 | 2160x3840 | 3840x2880 | 2880x3840 | 3840x2560 | 2560x3840 | 3072x3840 | 3840x3072 | 3840x1646 |

模型 ID 中的比例通常使用 `x`，例如 `1x1`、`16x9`；请求体里的 `size` 使用像素尺寸。

## 9. 本应用后端接口

如果不是直接调中转，而是通过本地应用后端调用，接口前缀是：

```text
http://localhost:3000/api
```

这里的 `Authorization` 是本应用登录后的本地 token，不是中转 API Key。中转 API Key 保存在用户配置里。

### 9.1 保存中转配置

```http
PUT /api/profile
Authorization: Bearer <LOCAL_TOKEN>
Content-Type: application/json
```

```json
{
  "api_key": "<API_KEY>",
  "base_url": "https://api.aicopy.top",
  "proxy_url": "",
  "timeout": 600
}
```

### 9.2 加载远程模型

```http
GET /api/models/remote
Authorization: Bearer <LOCAL_TOKEN>
```

响应：

```json
{
  "models": [
    {
      "id": "firefly-nano-banana-1k-1x1",
      "object": "model",
      "owned_by": "aicopy"
    }
  ],
  "base_url": "https://api.aicopy.top"
}
```

### 9.3 测试连接

```http
POST /api/connection/test
Authorization: Bearer <LOCAL_TOKEN>
Content-Type: application/json
```

应用会测试：

```text
GET  https://api.aicopy.top/v1/models
POST https://api.aicopy.top/v1/images/generations
```

### 9.4 上传参考图

```http
POST /api/upload/image
Authorization: Bearer <LOCAL_TOKEN>
Content-Type: multipart/form-data
```

字段：

```text
image: 文件
```

响应：

```json
{
  "b64": "data:image/jpeg;base64,<base64>",
  "path": "uploads/1/20260516_142532_demo.png"
}
```

### 9.5 创建图片生成任务

```http
POST /api/image/generate
Authorization: Bearer <LOCAL_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "model": "firefly-nano-banana-1k-1x1",
  "prompt": "一张 1:1 高级香水电商主图，白底，柔和阴影，真实摄影",
  "aspect_ratio": "1:1",
  "resolution": "1k",
  "variant": "(默认)",
  "ref_image_b64": "",
  "ref_images_b64": []
}
```

响应：

```json
{
  "ok": true,
  "task_id": 92
}
```

任务是异步生成。轮询：

```http
GET /api/image/tasks/92
Authorization: Bearer <LOCAL_TOKEN>
```

成功响应重点字段：

```json
{
  "ID": 92,
  "model_display": "firefly-nano-banana-1k-1x1",
  "model_name": "firefly-nano-banana-1k-1x1",
  "prompt": "...",
  "aspect_ratio": "1:1",
  "resolution": "1k",
  "status": "success",
  "image_url": "https://api.aicopy.top/v1/files/xxx.png",
  "local_path": "../outputs/images/img_92_20260524_162648.png",
  "error": ""
}
```

获取图片文件：

```http
GET /api/image/file/92
Authorization: Bearer <LOCAL_TOKEN>
```

如果本地已保存，会直接返回本地文件；否则重定向到 `image_url`。

## 10. 快速测试示例

### 10.1 PowerShell 查询模型

```powershell
$base = "https://api.aicopy.top/v1"
$key = "<API_KEY>"

Invoke-RestMethod `
  -Method Get `
  -Uri "$base/models" `
  -Headers @{
    Authorization = "Bearer $key"
    Accept = "application/json"
  }
```

### 10.2 PowerShell 文生图

```powershell
$base = "https://api.aicopy.top/v1"
$key = "<API_KEY>"

$body = @{
  model = "firefly-nano-banana-1k-1x1"
  prompt = "一张白底高级香水电商主图，真实摄影，柔和棚拍光"
  n = 1
  size = "1024x1024"
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
  -Method Post `
  -Uri "$base/images/generations" `
  -Headers @{
    Authorization = "Bearer $key"
    "Content-Type" = "application/json"
    Accept = "application/json"
  } `
  -Body $body
```

### 10.3 JavaScript 文生图

```js
const base = "https://api.aicopy.top/v1";
const apiKey = process.env.AICOPY_API_KEY;

const resp = await fetch(`${base}/images/generations`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Authorization": `Bearer ${apiKey}`
  },
  body: JSON.stringify({
    model: "firefly-nano-banana-1k-1x1",
    prompt: "一张白底高级香水电商主图，真实摄影，柔和棚拍光",
    n: 1,
    size: "1024x1024"
  })
});

const data = await resp.json();
console.log(data);
```

## 11. 常见错误处理

接口错误通常形如：

```json
{
  "error": {
    "message": "错误原因"
  }
}
```

建议处理规则：

- HTTP 非 2xx：优先显示 `error.message`。
- 没有图片字段：提示“no image data in response”或“无法从响应中提取图片 URL”。
- 上游繁忙、超载、502/503/504、rate limit：可以延迟后重试。
- 生成图片链接有时效性：拿到后尽快下载保存。

