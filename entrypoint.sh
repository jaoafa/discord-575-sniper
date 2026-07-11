#!/bin/sh
set -e

# discord.py の client.run() が内部で切断時の再接続処理を行うため、ここでは単純に起動するだけでよい。
exec python -m src
