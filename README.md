# rlaux v1

`rlaux` 是一个本地 Linux 优先的轻量工具，用于后台启动和管理 Python 训练任务。

## 功能

- 后台启动训练任务并写入日志
- SQLite 记录任务信息（task id / pid / pgid / 状态 / 命令）
- CLI 查看和停止任务
- 本地 Dashboard 查看 managed/unmanaged Python 进程
- 在线查看任务日志尾部

## 安装

```bash
cd /workspace/experiment/rlaux
pip install -e .
```

## 快速开始

### 1) 启动任务

```bash
rlaux run --log logs/exp1.log -- python train.py --env hopper --seed 1
```

启动成功会打印：

- `task_id`
- `pid`
- `pgid`
- `log_path`

### 2) 查看任务

```bash
rlaux list
```

### 3) 停止任务

```bash
rlaux stop 1
```

### 4) 启动面板

```bash
rlaux dashboard
```

默认地址：`http://127.0.0.1:17878`

## 命令说明

### `rlaux run`

```bash
rlaux run --log <logfile> -- <actual command>
```

示例：

```bash
rlaux run --log /tmp/test.log -- python -c "import time; print('hello'); time.sleep(30)"
```

说明：

- `--` 之后内容原样作为训练命令
- 相对日志路径按当前工作目录解析
- 任务以独立进程组启动（`start_new_session=True`）

### `rlaux list`

```bash
rlaux list
```

展示字段：`id / pid / status / managed / started_at / log / cmd`

### `rlaux stop`

```bash
rlaux stop <task_id>
```

说明：

- 仅允许停止 `rlaux` 管理的任务
- 优先给进程组发 `SIGTERM`，超时后升级 `SIGKILL`

### `rlaux dashboard`

```bash
rlaux dashboard --host 127.0.0.1 --port 17878
```

页面包含：

- Managed Tasks（可 Stop、可看日志）
- Detected Python Processes（仅 managed 可 Stop）

## 数据与目录

默认目录：

```text
~/.rlaux/
  rlaux.db
  logs/
```

可通过环境变量覆盖：

```bash
export RLAUX_HOME=/path/to/custom/home
```

## 最小可运行例子

```bash
# 启动一个模拟训练任务
rlaux run --log /tmp/rlaux_demo.log -- python -c "import time\nfor i in range(120):\n print(f'step={i}', flush=True)\n time.sleep(1)"

# 查看任务
rlaux list

# 看日志尾部（浏览器）
# http://127.0.0.1:17878/tasks/<task_id>/log?lines=120

# 停止任务
rlaux stop <task_id>
```

## 注意

- 当前版本定位 MVP：单机、本地、Linux
- 不包含多机调度、权限系统、自动重启、告警等高级能力
