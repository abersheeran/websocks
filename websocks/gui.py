import os
import sys
import subprocess
import platform
import configparser
from functools import partial
from pathlib import Path

import PySimpleGUIWx as sg

from .rule import FilterRule
from .utils import set_proxy

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
            f"{sys.executable} -m websocks client --tcp-server {default['tcp-server']}"
            f" --proxy-policy {default.get('proxy-policy', 'AUTO')}"
        )
        if "nameservers" in default:
            command += " " + " ".join(
                [
                    f"--nameserver {dns.strip()}"
                    for dns in default["nameservers"].split(";")
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
            command += " " + default["address"]

        log_file = open(log_path, "w+", encoding="utf8")
        cls.process = subprocess.Popen(command.split(" "), stderr=log_file, stdout=log_file)
        if cls.process.poll() is None:
            port = (
                default.get("address", "127.0.0.1 3128")
                .strip()
                .split(" ", maxsplit=1)[1]
            )
            set_proxy(True, f"http://127.0.0.1:{port}")
        return cls.process

    @classmethod
    def restart(cls) -> subprocess.Popen:
        cls.stop()
        return cls.start()

    @classmethod
    def stop(cls) -> None:
        if cls.process is not None:
            cls.process.terminate()
            cls.process.wait()
        set_proxy(False, "")


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
        "WebSocks Client Manager",
        [
            "重启服务",
            "关闭服务",
            "---",
            "编写配置",
            "编写规则",
            "查看日志",
            "更新名单",
            "---",
            "关闭程序",
        ],
    ]
    tray = sg.SystemTray(
        menu=menu,
        data_base64=b"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",
    )
    message_clicked = lambda: None

    try:
        if C.start().poll() is not None:
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
        try:
            if menu_item in (sg.EVENT_SYSTEM_TRAY_ICON_DOUBLE_CLICKED,):
                pass
            elif menu_item == "关闭程序":
                C.stop()
                break
            elif menu_item == "__MESSAGE_CLICKED__":
                message_clicked()
            elif menu_item == "编写配置":
                if not os.path.exists(config_path):
                    os.makedirs(os.path.dirname(config_path), exist_ok=True)
                    with open(config_path, "w+") as file:
                        file.writelines(["[DEFAULT]", ""])
                open_in_system_editor(config_path)
            elif menu_item == "编写规则":
                config = configparser.ConfigParser()
                config.read(config_path)
                default = config["DEFAULT"]
                if "rulefiles" not in default:
                    rulefile = os.path.expanduser("~/.websocks/rules.txt")
                    Path(rulefile).touch()
                    default["rulefiles"] = rulefile
                    with open(config_path, "w+") as file:
                        config.write(file)
                else:
                    rulefile = default["rulefiles"].split(";")[0]
                open_in_system_editor(rulefile)
            elif menu_item == "重启服务":
                if C.restart().poll() is not None:
                    message_clicked = partial(open_in_system_editor, log_path)
                    tray.show_message(
                        "服务启动失败",
                        "可点击此消息查看详细错误",
                        messageicon=sg.SYSTEM_TRAY_MESSAGE_ICON_CRITICAL,
                    )
                else:
                    message_clicked = lambda: None
                    tray.show_message(
                        "服务启动成功",
                        "HTTP/Socks 代理服务器已经成功在本地启动",
                        messageicon=sg.SYSTEM_TRAY_MESSAGE_ICON_INFORMATION,
                    )
            elif menu_item == "关闭服务":
                C.stop()
                message_clicked = lambda: None
                tray.show_message(
                    "本地服务关闭",
                    "HTTP/Socks 本地代理服务已关闭，系统代理设置已重置",
                    messageicon=sg.SYSTEM_TRAY_MESSAGE_ICON_INFORMATION,
                )
            elif menu_item == "查看日志":
                if not os.path.exists(log_path):
                    os.makedirs(os.path.dirname(log_path), exist_ok=True)
                    with open(log_path, "w+") as file:
                        ...
                open_in_system_editor(log_path)
            elif menu_item == "更新名单":
                FilterRule.download_gfwlist()
                FilterRule.download_whitelist()
                message_clicked = lambda: None
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
