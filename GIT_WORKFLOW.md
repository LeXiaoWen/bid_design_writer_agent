# Git 推送流程

## 远程仓库

```
https://github.com/LeXiaoWen/bid_design_writer_agent.git
```

## 首次推送

```bash
git add .
git commit -m "初始提交"
git branch -M main
git push -u origin main
```

## 日常提交

```bash
git add .
git commit -m "描述本次改动"
git push
```

## 其他常用命令

```bash
# 查看状态
git status

# 查看提交历史
git log --oneline

# 创建并切换到新分支
git checkout -b feature/xxx

# 拉取远程更新
git pull
```
