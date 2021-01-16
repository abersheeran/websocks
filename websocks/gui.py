import os
import sys
import signal
import subprocess
import platform
import configparser
from functools import partial

import PySimpleGUI as sg

from .rule import FilterRule

signal.signal(signal.SIGINT, lambda _, __: sys.exit(0))

config_path = os.path.expanduser("~/.websocks/config.ini")
log_path = os.path.join(os.path.dirname(config_path), "run.log")


class C:
    process: subprocess.Popen = None

    @classmethod
    def start(cls) -> subprocess.Popen:
        if cls.process is not None and cls.process.poll() is None:
            raise RuntimeError("Don't start WebSocks Client repeatedly")

        config = configparser.ConfigParser()
        config.read(config_path)
        default = config["DEFAULT"]
        if "tcp-server" not in default:
            raise RuntimeError("配置文件中必须指定 tcp-server 项")

        command = (
            f"{sys.executable} -m websocks client --tcp-server {default.get('tcp-server')}"
            f" --proxy-policy {default.get('proxy-policy', 'AUTO')}"
        )
        if "nameservers" in default:
            command += " " + " ".join(
                [
                    f"--nameserver {dns.strip()}"
                    for dns in default["nameservers"].split(",")
                ]
            )
        if "rulefiles" in default:
            command += " " + " ".join(
                [
                    f"--rulefile {filepath.strip()}"
                    for filepath in default["rulefiles"].split(";")
                ]
            )
        if "address" in default:
            command += default["address"]

        log_file = open(log_path, "w+", encoding="utf8")
        log_file.write(command + "\n")
        cls.process = subprocess.Popen(
            command, stderr=log_file, stdout=log_file, shell=True
        )
        return cls.process

    @classmethod
    def restart(cls) -> subprocess.Popen:
        cls.stop()
        return cls.start()

    @classmethod
    def stop(cls) -> None:
        if cls.process is not None:
            cls.process.terminate()


def open_in_system_editor(filepath: str) -> None:
    if platform.system() == "Windows":
        os.startfile(filepath)
    elif platform.system() == "Linux":
        subprocess.call(["xdg-open", filepath])
    elif platform.system() == "Darwin":
        subprocess.call(["open", filepath])


def main():
    sg.change_look_and_feel("SystemDefault")

    menu = [
        ["WebSocks Client Manager"],
        [
            "重启服务",
            "编写配置",
            "查看日志",
            "更新名单",
            "---",
            "关闭程序",
        ],
    ]
    tray = sg.SystemTray(
        menu=menu,
        data_base64=b"iVBORw0KGgoAAAANSUhEUgAAADIAAAAtCAMAAADbYcjNAAAAAXNSR0IArs4c6QAAAARnQ\
                        U1BAACxjwv8YQUAAAMAUExURQAAADBpmDFqmDBqmTFqmjJrmzJsmzJsnDNtnTRrmjVtmj\
                        ZsmzRunTRunjVvnzdwnjVwnzpxnzVwoDZxoTdyojlyoThzozhzpDh0pDp1pjp2pj51ozt\
                        3qDt4qDx4qDx5qj16qj57rD58rT98rkF1oEB4pUB4pkR6pkJ6qEN8q0B9rUB9rkB+rkV7\
                        qUZ8qUp9p0x+p0h/rEB+sEeArkqArEqBr0uCrkKAsUKAskOCs0OCtESCtEWEtkaFuEaGu\
                        E2FsUiHukiIukmJvEmKvEqLvkuMvk2KuUyLvEyMv1OErVWDqlWHr1qHrVaIsVCMvFSPvV\
                        2LsViOuVSQvmyUtmyXuXKbvXefv3ugv06NwE6OwFmUwl2XxGScyGmbw22hynikxnmmyv/\
                        UO//UPP/VPf/UPv/VP//UQP/VQf/VQv/WQP/WQf/WQv/WQ//XRP/WRf/WSf/YRf/YRv/Y\
                        R//YSP/ZSf/ZSv/aS//aTP/aTf/bTv/YUf/ZUv/bUP/cUP/cUv/dVP/dVv/eVv/bW//dW\
                        f/cWv/eWP/fWv/dXf/fXf/eXv/cYP/fYP/dZP/dZv/eZf/fZv/eaP/gW//gXP/gXv/gYP\
                        /iYf/iYv/hZP/jZP/iZv/kZv/jaf/ja//kaP/lav/kbP/lb//mbP/mbv/ncP/mcv/iff/\
                        ocv/odP/odv/oeP/of//qf4GnxYOox4SoxYSpx4asyo+ux4isyouuyouvzIyuyYyvy4yv\
                        zI6wy46wzIyz0pCuyJSxyZWyy5u3zZ24zpW30pG52J250J+60aC60KS90aDC3a3E163F2\
                        K3F2bPI2bvO3rzP3qvJ4LHN4rnR5P/qgf/qgv/qiP/sif/sjf/sj//olf/ql//ulv/omf\
                        /qnv/tnP/qoP/ro//qpP/sov/upf/tqP/uqP/vrf/vrv/us//wpP/wpv/xrf/wsP/wsv/\
                        ys//xtP/ytf/ytv/zuf/zuv/0vP/0vsDS38XZ6cnb6f/xw//zwv/yxf/1w//zyP/1yf/2\
                        zP/3z//30wAAAM55ho4AAAEAdFJOU////////////////////////////////////////\
                        /////////////////////////////////////////////////////////////////////\
                        /////////////////////////////////////////////////////////////////////\
                        /////////////////////////////////////////////////////////////////////\
                        /////////////////////////////////////////////////////////////////////\
                        ////////////////////////wBT9wclAAAACXBIWXMAABcQAAAXEAEYYRHbAAAAGHRFWH\
                        RTb2Z0d2FyZQBwYWludC5uZXQgNC4xLjFjKpxLAAADnElEQVRIS62OeVhUZRSHw6IosQz\
                        GBgoIszKXqGylghKwbHErNVPbEFQQTXYogzZtt2SmiSEHnBHJPdM2Ldv3xbW91Pay0tT2\
                        9dc53znfvTP809Pz9P7x3Xvu8773fHvhP/M/JBce0GX/8/WduX3ipDt/1nclNrk4TnhR5\
                        y1FVzHX/KqzISY5Uou4uLVm/sgEzF1mFqKTruozL9D8gfrM1aIwbvJaF7WFJ4FJqgtb1X\
                        OTN1R1eBqYrLbwvpo2+SF2B/NEbFNY+IWoNum6t0UD4imgTO3CCROKiqaJqsnx8fHx+7h\
                        o/RBALsnFxcUlJSWlNxpXkkv2I/a1uPnLWEA626WlU6aUlf3uJomJiccdlJDAoQvFBwPs\
                        klw2deq06dNnO8nIbj3oHE4hkWDQ7HVcSzLb5eXlFRWVTtKj+/P8OJDojfO6Wahfi3uMW\
                        1FZWVVVVV39jk2Skl6RR9JhwOjunDJUPYfZ1q6uqampvcUmWZ4sOpcnJ9Pj8WQqHYAZ4t\
                        bW1tXV19ffbJNXPZ6sUUM8nqOBRzweT7LDBQDZdcYmZlz3rk2wNCUlxes9iXYcwlBmOAq\
                        4W12moeE2liXBg9QcA6yiB+P1eqk8FtgmdoOh8SbjaoJlqacAj6ZqYqBffCJyo+GGO0S1\
                        CVYDKw8VUg0nAJ87NnOrmk4CPJYmSNeHdjQ2Xm/kmcx9qkUlKzKU9PT0tLSTaYeVZ84i/\
                        KpFJQ9nZmYermRknAh8qu6sOU1EUDXCJit6UuJwFu1gm+WmJp/PR7f6xr9NVE2eOYLoae\
                        EdVvb5/H7/XOC7QCDwoXE16d+L4IzpC3xmZLb99wYC9wPbm5mP2ZVkRH9DP0OvK/CLcUk\
                        mmpvn0Y5gsKWlJRRykwEOXAJBI5NNBNtoRyhEJxa3bnKS005ltBoAqGz+3E47Qq2tO9gL\
                        R+jQJAbaItdgWhdje1tbOPwHe5GFdEhyuiE7O1sTkQ1t4fZwOBKJbCTt6/lfOsllZ0TzE\
                        9rZpV8bORKZz2z46q2ODpYlwZmCJFfiTyuL3WHZzK4ma7QRgJ2dZcG4mmBoriEnJ4eSc4\
                        BvO9vMe0a1CQZKIwwDdqkWxRIxnWT9QOJsITd3KN1NRRc1nQTrzs3L40y4CNitprLwbxX\
                        dBD/mM3nCWPoQs+cBkYioBLi8oMBk+flcAHtUJ942HwwxCd4cM2hQATFO5+81WPSbfmBi\
                        E+Cl8ZcOHvusDsBfG+hKm/foJHRO/hXgH831bVAP1oP5AAAAAElFTkSuQmCC",
    )
    message_clicked = lambda: None

    try:
        if C.restart().poll() is not None:
            message_clicked = partial(open_in_system_editor, log_path)
            tray.show_message(
                "服务启动失败",
                "可点击此消息查看详细错误",
                messageicon=sg.SYSTEM_TRAY_MESSAGE_ICON_CRITICAL,
            )
        else:
            tray.show_message(
                "服务启动成功",
                "HTTP/Socks 代理服务器已经成功在本地启动",
                messageicon=sg.SYSTEM_TRAY_MESSAGE_ICON_INFORMATION,
            )
    except Exception as e:
        tray.show_message(
            e.__class__.__name__,
            str(e),
            messageicon=sg.SYSTEM_TRAY_MESSAGE_ICON_CRITICAL,
        )

    while True:
        menu_item = tray.read()
        print(menu_item)
        try:
            if menu_item in (sg.EVENT_SYSTEM_TRAY_ICON_DOUBLE_CLICKED,):
                pass
            elif menu_item == "关闭程序":
                sys.exit(0)
            elif menu_item == "__MESSAGE_CLICKED__":
                message_clicked()
            elif menu_item == "编写配置":
                if not os.path.exists(config_path):
                    os.makedirs(os.path.dirname(config_path), exist_ok=True)
                    with open(config_path, "w+") as file:
                        file.writelines(["[DEFAULT]", ""])
                open_in_system_editor(config_path)
            elif menu_item == "重启服务":
                if C.restart().poll() is not None:
                    message_clicked = partial(open_in_system_editor, log_path)
                    tray.show_message(
                        "服务启动失败",
                        "可点击此消息查看详细错误",
                        messageicon=sg.SYSTEM_TRAY_MESSAGE_ICON_CRITICAL,
                    )
                else:
                    tray.show_message(
                        "服务启动成功",
                        "HTTP/Socks 代理服务器已经成功在本地启动",
                        messageicon=sg.SYSTEM_TRAY_MESSAGE_ICON_INFORMATION,
                    )
            elif menu_item == "查看日志":
                if not os.path.exists(config_path):
                    os.makedirs(os.path.dirname(config_path), exist_ok=True)
                    with open(config_path, "w+") as file:
                        ...
                open_in_system_editor(log_path)
            elif menu_item == "更新名单":
                FilterRule.download_gfwlist()
                FilterRule.download_whitelist()
                tray.show_message(
                    "更新名单完成",
                    "更新名单完成",
                    messageicon=sg.SYSTEM_TRAY_MESSAGE_ICON_INFORMATION,
                )
        except Exception as e:
            tray.show_message(
                e.__class__.__name__,
                str(e),
                messageicon=sg.SYSTEM_TRAY_MESSAGE_ICON_CRITICAL,
            )


if __name__ == "__main__":
    main()
