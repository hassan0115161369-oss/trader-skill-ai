import asyncio
import json
from datetime import datetime, timedelta
import aiohttp
import flet as ft
import websockets

# هوية Cyber Bull البصرية
BG_DARK = "#050811"
CARD_GLASS = "#0D152C"
NEON_CYAN = "#00F5D4"
ELECTRIC_BLUE = "#00BBF9"
DANGER_RED = "#FF2A5F"
SUCCESS_GREEN = "#00E676"
TEXT_PRIMARY = "#F8FAFC"
TEXT_MUTED = "#94A3B8"


class AutoRiskShield:
    def __init__(self, max_daily_loss: float = 50.0, daily_profit_target: float = 100.0, max_consecutive_losses: int = 3):
        self.max_daily_loss = max_daily_loss
        self.daily_profit_target = daily_profit_target
        self.max_consecutive_losses = max_consecutive_losses
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.cooldown_until = None
        self.allow_real_trading = False

    def can_trade(self, account_type: str) -> tuple[bool, str]:
        if account_type == "REAL" and not self.allow_real_trading:
            return False, "قفل الأمان نشط: فعّل التداول الحقيقي يدوياً أولاً."
        if self.cooldown_until and datetime.now() < self.cooldown_until:
            mins = int((self.cooldown_until - datetime.now()).total_seconds() // 60) + 1
            return False, f"فترة تبريد تلقائية ({mins} دقيقة متبقية) بعد {self.max_consecutive_losses} خسائر متتالية."
        if self.daily_pnl <= -abs(self.max_daily_loss):
            return False, f"تم بلوغ حد الخسارة اليومي (-{self.max_daily_loss}$). تم إيقاف الروبوت."
        if self.daily_pnl >= self.daily_profit_target:
            return False, f"تم تحقيق هدف الربح اليومي (+{self.daily_profit_target}$)."
        return True, "OK"

    def record_result(self, pnl: float):
        self.daily_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.cooldown_until = datetime.now() + timedelta(minutes=15)
        else:
            self.consecutive_losses = 0
            self.cooldown_until = None


class MultiBrokerEngine:
    def __init__(self, platform: str, token: str, app_id: str = "1089", bridge_url: str = "", account_id: str = ""):
        self.platform = platform
        self.token = token.strip()
        self.app_id = app_id.strip() or "1089"
        self.bridge_url = bridge_url.strip().rstrip("/")
        self.account_id = account_id.strip()
        self.account_type = "DEMO"
        self.balance = 0.0
        self.currency = "USD"
        self.is_connected = False
        self.ws = None

    async def connect(self) -> tuple[bool, str]:
        if self.platform == "Deriv":
            url = f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}"
            self.ws = await websockets.connect(url, ping_interval=20)
            await self.ws.send(json.dumps({"authorize": self.token}))
            res = json.loads(await self.ws.recv())
            if "error" in res:
                self.is_connected = False
                return False, res["error"].get("message", "خطأ توثيق Deriv")
            auth = res["authorize"]
            self.account_id = auth.get("loginid", "UNKNOWN")
            self.balance = float(auth.get("balance", 0.0))
            self.currency = auth.get("currency", "USD")
            self.account_type = "DEMO" if str(self.account_id).startswith("VRTC") else "REAL"
            self.is_connected = True
            return True, f"متصل بـ Deriv ({self.account_id} - {self.account_type})"

        if self.platform == "MT5":
            if not self.bridge_url or not self.account_id:
                return False, "أدخل رابط الجسر Bridge URL ورقم حساب MT5"
            headers = {"Authorization": f"Bearer {self.token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.bridge_url}/account/{self.account_id}", headers=headers, timeout=10) as r:
                    if r.status != 200:
                        return False, f"فشل الاتصال بجسر MT5 (رمز {r.status})"
                    data = await r.json()
                    self.balance = float(data.get("balance", 0.0))
                    self.currency = data.get("currency", "USD")
                    self.is_connected = True
                    return True, f"متصل بـ MT5 ({self.account_id})"

        if self.platform == "Binance":
            if not self.token:
                return False, "أدخل مفتاح Binance API Key"
            self.is_connected = True
            self.balance = 0.0
            self.currency = "USDT"
            return True, "تم تفعيل موصل Binance"

        if self.platform == "Quotex":
            if not self.token:
                return False, "أدخل رمز الجلسة / Token الخاص بـ Quotex"
            self.is_connected = True
            self.balance = 0.0
            self.currency = "USD"
            return True, "تم تفعيل موصل Quotex"

        return False, "منصة غير مدعومة"

    async def get_price(self, symbol: str) -> float:
        if self.platform == "Deriv" and self.ws and self.is_connected:
            await self.ws.send(json.dumps({"ticks": symbol}))
            res = json.loads(await self.ws.recv())
            if "tick" in res:
                return float(res["tick"]["quote"])
        elif self.platform == "MT5" and self.bridge_url and self.is_connected:
            headers = {"Authorization": f"Bearer {self.token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.bridge_url}/price/{symbol}", headers=headers, timeout=8) as r:
                    if r.status == 200:
                        data = await r.json()
                        return float(data.get("bid", 0.0))
        return 0.0

    async def execute_order(self, symbol: str, side: str, amount: float, duration: int = 1, duration_unit: str = "m") -> dict:
        if self.platform == "Deriv" and self.ws and self.is_connected:
            contract_type = "CALL" if side.upper() == "BUY" else "PUT"
            req = {
                "buy": 1,
                "price": amount,
                "parameters": {
                    "amount": amount,
                    "basis": "stake",
                    "contract_type": contract_type,
                    "currency": self.currency,
                    "duration": duration,
                    "duration_unit": duration_unit,
                    "symbol": symbol,
                },
            }
            await self.ws.send(json.dumps(req))
            res = json.loads(await self.ws.recv())
            if "error" in res:
                return {"ok": False, "msg": res["error"].get("message", "فشل تنفيذ الأمر")}
            buy = res.get("buy", {})
            if "balance_after" in buy:
                self.balance = float(buy["balance_after"])
            return {"ok": True, "msg": f"تم تنفيذ {contract_type} على {symbol} | العقد: {buy.get('contract_id')}"}

        if self.platform == "MT5" and self.bridge_url and self.is_connected:
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            payload = {"account_id": self.account_id, "symbol": symbol, "action": side.upper(), "volume": amount}
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.bridge_url}/trade", json=payload, headers=headers, timeout=10) as r:
                    data = await r.json()
                    if r.status in (200, 201):
                        return {"ok": True, "msg": f"تم إرسال أمر {side.upper()} على MT5 ({symbol})"}
                    return {"ok": False, "msg": data.get("detail", "فشل أمر MT5")}

        return {"ok": False, "msg": f"التنفيذ المباشر على {self.platform} يتطلب ربط نقطة النهاية أو التوكن النشط"}

    async def disconnect(self):
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.is_connected = False


class TraderSkillAI:
    def __init__(self, page: ft.Page):
        self.page = page
        self.lang = "AR"
        self.bot_running = False
        self.broker: MultiBrokerEngine | None = None
        self.risk = AutoRiskShield()
        self.logs: list[str] = []

        self.page.title = "TRADER SKILL AI — ULTIMATE FINAL EDITION"
        self.page.bgcolor = BG_DARK
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.rtl = True
        self.page.padding = 0

        self.show_splash()

    def log(self, text: str, kind: str = "INFO"):
        now = datetime.now().strftime("%H:%M:%S")
        self.logs.insert(0, f"[{now}] [{kind}] {text}")
        if len(self.logs) > 120:
            self.logs.pop()
        if hasattr(self, "logs_column"):
            self.logs_column.controls = [
                ft.Text(
                    line,
                    size=12,
                    font_family="monospace",
                    color=DANGER_RED if "[ERR]" in line else (SUCCESS_GREEN if "[ORD]" in line else NEON_CYAN),
                )
                for line in self.logs
            ]
            self.page.update()

    def show_splash(self):
        self.page.clean()
        self.page.add(
            ft.Container(
                expand=True,
                gradient=ft.LinearGradient(
                    begin=ft.alignment.top_center,
                    end=ft.alignment.bottom_center,
                    colors=[BG_DARK, "#0A1736", BG_DARK],
                ),
                content=ft.Column(
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(
                            width=116,
                            height=116,
                            border_radius=28,
                            bgcolor="#09132B",
                            border=ft.border.all(2, NEON_CYAN),
                            alignment=ft.alignment.center,
                            content=ft.Icon(ft.Icons.AUTO_AWESOME, size=58, color=NEON_CYAN),
                        ),
                        ft.Container(height=18),
                        ft.Text("TRADER SKILL AI", size=28, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                        ft.Text("AI FINANCIAL INTELLIGENCE & MULTI-BROKER AUTO BOT", size=12, color=NEON_CYAN),
                        ft.Container(height=28),
                        ft.ProgressBar(width=220, color=NEON_CYAN, bgcolor="#1E293B"),
                    ],
                ),
            )
        )
        self.page.update()
        self.page.run_task(self._go_login)

    async def _go_login(self):
        await asyncio.sleep(1.8)
        self.show_login()

    def show_login(self):
        self.page.clean()
        email = ft.TextField(label="البريد الإلكتروني / Email", border_color=ELECTRIC_BLUE, focused_border_color=NEON_CYAN)
        password = ft.TextField(
            label="كلمة المرور / Password",
            password=True,
            can_reveal_password=True,
            border_color=ELECTRIC_BLUE,
            focused_border_color=NEON_CYAN,
        )
        err = ft.Text("", color=DANGER_RED, size=12)

        def submit(e):
            if not email.value or "@" not in email.value:
                err.value = "أدخل بريد إلكتروني صحيح"
                self.page.update()
                return
            if not password.value or len(password.value) < 6:
                err.value = "كلمة المرور يجب ألا تقل عن 6 أحرف"
                self.page.update()
                return
            self.show_dashboard()

        self.page.add(
            ft.Container(
                expand=True,
                alignment=ft.alignment.center,
                padding=20,
                content=ft.Container(
                    width=380,
                    padding=26,
                    border_radius=20,
                    bgcolor=CARD_GLASS,
                    border=ft.border.all(1, ELECTRIC_BLUE),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.Icons.BOLT, size=46, color=NEON_CYAN),
                            ft.Text("تسجيل الدخول", size=22, weight=ft.FontWeight.BOLD),
                            ft.Text("Cyber Bull Terminal", size=12, color=TEXT_MUTED),
                            ft.Container(height=12),
                            email,
                            password,
                            err,
                            ft.Container(height=10),
                            ft.ElevatedButton(
                                text="دخول المنصة / LOGIN",
                                width=320,
                                height=46,
                                bgcolor=ELECTRIC_BLUE,
                                color=BG_DARK,
                                on_click=submit,
                            ),
                            ft.TextButton("AR / EN", on_click=self.switch_lang),
                        ],
                    ),
                ),
            )
        )
        self.page.update()

    def switch_lang(self, e):
        self.lang = "EN" if self.lang == "AR" else "AR"
        self.page.rtl = self.lang == "AR"
        self.show_dashboard()

    def show_dashboard(self):
        self.page.clean()

        self.balance_lbl = ft.Text("0.00 USD", size=26, weight=ft.FontWeight.BOLD, color=NEON_CYAN)
        self.status_badge = ft.Container(
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            border_radius=8,
            bgcolor="#1E293B",
            content=ft.Text("OFFLINE", size=11, weight=ft.FontWeight.BOLD, color=TEXT_MUTED),
        )
        self.logs_column = ft.ListView(expand=True, spacing=5, auto_scroll=True)

        platform_dd = ft.Dropdown(
            label="المنصة / Broker",
            value="Deriv",
            options=[
                ft.dropdown.Option("Deriv", "Deriv (WebSocket API v3)"),
                ft.dropdown.Option("MT5", "MetaTrader 5 (Bridge API)"),
                ft.dropdown.Option("Binance", "Binance API"),
                ft.dropdown.Option("Quotex", "Quotex Connector"),
            ],
            border_color=ELECTRIC_BLUE,
        )
        token_tf = ft.TextField(label="API Token / Key", password=True, can_reveal_password=True, border_color=ELECTRIC_BLUE)
        app_id_tf = ft.TextField(label="Deriv App ID (افتراضي 1089)", value="1089", border_color=ELECTRIC_BLUE)
        bridge_tf = ft.TextField(label="MT5 Bridge URL (اختياري لـ MT5)", border_color=ELECTRIC_BLUE)
        acc_id_tf = ft.TextField(label="Account ID (اختياري لـ MT5)", border_color=ELECTRIC_BLUE)

        symbol_dd = ft.Dropdown(
            label="الرمز / Symbol",
            value="R_100",
            options=[
                ft.dropdown.Option("R_100", "Volatility 100 (R_100)"),
                ft.dropdown.Option("R_75", "Volatility 75 (R_75)"),
                ft.dropdown.Option("1HZ100V", "Volatility 100 (1s)"),
                ft.dropdown.Option("frxXAUUSD", "Gold (XAUUSD)"),
                ft.dropdown.Option("frxEURUSD", "EUR/USD"),
                ft.dropdown.Option("cryBTCUSD", "BTC/USD"),
            ],
            border_color=ELECTRIC_BLUE,
        )
        stake_tf = ft.TextField(label="قيمة الصفقة / Stake", value="1.0", width=150, border_color=ELECTRIC_BLUE)
        max_loss_tf = ft.TextField(label="حد الخسارة اليومي ($)", value="50.0", width=165, border_color=ELECTRIC_BLUE)
        target_tf = ft.TextField(label="هدف الربح اليومي ($)", value="100.0", width=165, border_color=ELECTRIC_BLUE)

        real_switch = ft.Switch(
            label="تفعيل الحساب الحقيقي (REAL LOCK)",
            value=False,
            active_color=DANGER_RED,
            on_change=lambda e: self._toggle_real(e.control.value),
        )

        async def do_connect(e):
            if not token_tf.value:
                self.log("أدخل رمز الوصول API Token أولاً", "ERR")
                return
            self.broker = MultiBrokerEngine(
                platform=platform_dd.value,
                token=token_tf.value,
                app_id=app_id_tf.value,
                bridge_url=bridge_tf.value,
                account_id=acc_id_tf.value,
            )
            ok, msg = await self.broker.connect()
            if ok:
                self.balance_lbl.value = f"{self.broker.balance:,.2f} {self.broker.currency}"
                is_demo = self.broker.account_type == "DEMO"
                self.status_badge.bgcolor = "#064E3B" if is_demo else "#7F1D1D"
                self.status_badge.content = ft.Text(
                    f"{self.broker.account_type} • {self.broker.account_id}",
                    size=11,
                    weight=ft.FontWeight.BOLD,
                    color=SUCCESS_GREEN if is_demo else DANGER_RED,
                )
                self.log(msg, "INFO")
            else:
                self.log(msg, "ERR")
            self.page.update()

        async def do_disconnect(e):
            self.bot_running = False
            if self.broker:
                await self.broker.disconnect()
            self.status_badge.bgcolor = "#1E293B"
            self.status_badge.content = ft.Text("OFFLINE", size=11, color=TEXT_MUTED)
            self.log("تم فصل الاتصال بالمنصة", "INFO")
            self.page.update()

        bot_btn = ft.ElevatedButton(
            text="تشغيل الروبوت الآلي / START BOT",
            bgcolor=SUCCESS_GREEN,
            color=BG_DARK,
            height=46,
            on_click=lambda e: self._toggle_bot(bot_btn, symbol_dd.value, stake_tf.value, max_loss_tf.value, target_tf.value),
        )

        tabs = ft.Tabs(
            selected_index=0,
            indicator_color=NEON_CYAN,
            label_color=NEON_CYAN,
            unselected_label_color=TEXT_MUTED,
            expand=True,
            tabs=[
                ft.Tab(
                    text="الروبوت واللوحة",
                    icon=ft.Icons.ROBOT_2,
                    content=ft.Container(
                        padding=14,
                        content=ft.Column(
                            scroll=ft.ScrollMode.AUTO,
                            controls=[
                                ft.Container(
                                    padding=18,
                                    border_radius=16,
                                    bgcolor=CARD_GLASS,
                                    border=ft.border.all(1, ELECTRIC_BLUE),
                                    content=ft.Column([
                                        ft.Row([ft.Text("الرصيد الفعلي للحساب", color=TEXT_MUTED), self.status_badge], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                        self.balance_lbl,
                                    ]),
                                ),
                                ft.Container(height=10),
                                ft.Container(
                                    padding=16,
                                    border_radius=16,
                                    bgcolor=CARD_GLASS,
                                    content=ft.Column([
                                        ft.Text("إعدادات التداول الآلي وإدارة المخاطر", size=15, weight=ft.FontWeight.BOLD, color=NEON_CYAN),
                                        symbol_dd,
                                        ft.Row([stake_tf, real_switch], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                        ft.Row([max_loss_tf, target_tf], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                        bot_btn,
                                    ]),
                                ),
                                ft.Container(height=10),
                                ft.Container(
                                    height=210,
                                    padding=12,
                                    border_radius=14,
                                    bgcolor="#03060D",
                                    border=ft.border.all(1, "#1E293B"),
                                    content=ft.Column([
                                        ft.Text("سجل العمليات والذكاء الاصطناعي (Live Log)", size=12, color=TEXT_MUTED),
                                        self.logs_column,
                                    ]),
                                ),
                            ],
                        ),
                    ),
                ),
                ft.Tab(
                    text="المنصات",
                    icon=ft.Icons.HUB,
                    content=ft.Container(
                        padding=14,
                        content=ft.Column(
                            scroll=ft.ScrollMode.AUTO,
                            controls=[
                                ft.Text("ربط منصات التداول (Multi-Broker)", size=16, weight=ft.FontWeight.BOLD, color=NEON_CYAN),
                                platform_dd,
                                token_tf,
                                app_id_tf,
                                bridge_tf,
                                acc_id_tf,
                                ft.Row([
                                    ft.ElevatedButton("اتصال / CONNECT", bgcolor=ELECTRIC_BLUE, color=BG_DARK, on_click=do_connect),
                                    ft.OutlinedButton("فصل / DISCONNECT", on_click=do_disconnect),
                                ]),
                            ],
                        ),
                    ),
                ),
                ft.Tab(
                    text="التحليل والأخبار",
                    icon=ft.Icons.ANALYTICS,
                    content=ft.Container(
                        padding=16,
                        content=ft.Column(
                            scroll=ft.ScrollMode.AUTO,
                            controls=[
                                ft.Text("مركز التحليل الفني والمؤشرات والأخبار", size=16, weight=ft.FontWeight.BOLD, color=NEON_CYAN),
                                ft.Text("• الشموع اليابانية: Doji, Hammer, Engulfing, Pin Bar, Morning/Evening Star.", size=13),
                                ft.Text("• المؤشرات الفنية: RSI, MACD, EMA, Bollinger Bands, ATR, VWAP.", size=13),
                                ft.Text("• التقويم الاقتصادي والأخبار: فصل الحقائق عن التوقعات ومراقبة جودة البيانات LIVE/DELAYED.", size=13),
                                ft.Text("• إعادة العرض التاريخي (Market Replay) وشبكة العلاقات الاقتصادية والأكاديمية التعليمية.", size=13, color=TEXT_MUTED),
                            ],
                        ),
                    ),
                ),
            ],
        )

        top_bar = ft.Container(
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            bgcolor="#080D1E",
            content=ft.Row([
                ft.Row([ft.Icon(ft.Icons.BOLT, color=NEON_CYAN), ft.Text("TRADER SKILL AI", weight=ft.FontWeight.BOLD)]),
                ft.Row([
                    ft.IconButton(ft.Icons.LANGUAGE, on_click=self.switch_lang),
                    ft.IconButton(ft.Icons.LOGOUT, on_click=lambda _: self.show_login()),
                ]),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        )

        self.page.add(ft.Column([top_bar, tabs], expand=True))
        self.page.update()

    def _toggle_real(self, enabled: bool):
        self.risk.allow_real_trading = enabled
        self.log("تم فتح قفل الحساب الحقيقي" if enabled else "تم قفل الحساب الحقيقي", "INFO")

    def _toggle_bot(self, btn: ft.ElevatedButton, symbol: str, stake_s: str, max_loss_s: str, target_s: str):
        if not self.broker or not self.broker.is_connected:
            self.log("اربط حسابك أولاً من تبويب المنصات", "ERR")
            return
        self.bot_running = not self.bot_running
        if self.bot_running:
            try:
                self.risk.max_daily_loss = float(max_loss_s or 50.0)
                self.risk.daily_profit_target = float(target_s or 100.0)
                stake = float(stake_s or 1.0)
            except ValueError:
                self.log("تحقق من صحة الأرقام المدخلة", "ERR")
                self.bot_running = False
                return
            btn.text = "إيقاف الروبوت / STOP BOT"
            btn.bgcolor = DANGER_RED
            self.log(f"تشغيل الروبوت الآلي على {symbol} بقيمة صفقة {stake}", "INFO")
            self.page.run_task(self._loop, symbol, stake, btn)
        else:
            btn.text = "تشغيل الروبوت الآلي / START BOT"
            btn.bgcolor = SUCCESS_GREEN
            self.log("تم إيقاف الروبوت الآلي", "INFO")
        self.page.update()

    async def _loop(self, symbol: str, stake: float, btn: ft.ElevatedButton):
        ticks: list[float] = []
        while self.bot_running and self.broker and self.broker.is_connected:
            allowed, reason = self.risk.can_trade(self.broker.account_type)
            if not allowed:
                self.log(reason, "ERR")
                self.bot_running = False
                btn.text = "تشغيل الروبوت الآلي / START BOT"
                btn.bgcolor = SUCCESS_GREEN
                self.page.update()
                break

            price = await self.broker.get_price(symbol)
            if price > 0:
                ticks.append(price)
                if len(ticks) > 15:
                    ticks.pop(0)
                if len(ticks) >= 4:
                    side = None
                    if ticks[-1] > ticks[-2] > ticks[-3]:
                        side = "BUY"
                    elif ticks[-1] < ticks[-2] < ticks[-3]:
                        side = "SELL"
                    if side:
                        res = await self.broker.execute_order(symbol=symbol, side=side, amount=stake)
                        if res.get("ok"):
                            self.log(res.get("msg", "تم التنفيذ"), "ORD")
                            self.balance_lbl.value = f"{self.broker.balance:,.2f} {self.broker.currency}"
                            self.page.update()
                            await asyncio.sleep(15)
                        else:
                            self.log(res.get("msg", "فشل التنفيذ"), "ERR")
            await asyncio.sleep(2)


def main(page: ft.Page):
    TraderSkillAI(page)


if __name__ == "__main__":
    ft.app(target=main)
