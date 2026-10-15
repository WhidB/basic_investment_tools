"""미국 상장 주식·ETF의 일별 OHLC 기반 익절/손절 계산기."""
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo
import csv
import hashlib
import json
from pathlib import Path
import time
import io
import re
import webbrowser
from urllib.parse import quote

CACHE_DIR = Path(__file__).resolve().parent / ".price_cache"


class PriceRateLimitError(ValueError):
    pass


def retry_rate_limit(operation):
    from yfinance.exceptions import YFRateLimitError
    for attempt in range(3):
        try:
            return operation()
        except YFRateLimitError as exc:
            if attempt == 2:
                raise PriceRateLimitError(
                    "Yahoo Finance의 요청 제한이 계속되고 있습니다. "
                    "잠시 후 다시 시도하세요. 제한 해제 시간은 제공처가 결정합니다."
                ) from exc
            delay = (10, 30)[attempt]
            print(f"주가 제공처 요청 제한: {delay}초 후 재시도 ({attempt + 1}/2). Ctrl+C로 취소할 수 있습니다.", flush=True)
            time.sleep(delay)


@dataclass(frozen=True)
class Trade:
    entry_date: date
    entry_close: float
    last_date: date
    last_price: float
    result: str
    reason: str

    @property
    def return_pct(self):
        return (self.last_price / self.entry_close - 1) * 100


def calculate(prices, take_profit, stop_loss, mode="sequential"):
    """prices: (date, open, high, low, close). 종가 진입, 양방향 도달은 손절 우선."""
    if not isfinite(take_profit) or take_profit <= 0:
        raise ValueError("익절률은 0보다 큰 유한한 숫자여야 합니다.")
    if not isfinite(stop_loss) or not 0 < stop_loss < 100:
        raise ValueError("손절률은 0보다 크고 100보다 작아야 합니다.")
    if mode not in ("sequential", "daily"):
        raise ValueError("지원하지 않는 매수 방식입니다.")
    prices = list(prices)
    for i, (day, opening, high, low, close) in enumerate(prices):
        if not all(isfinite(p) and p > 0 for p in (opening, high, low, close)):
            raise ValueError("OHLC 가격은 양의 유한한 숫자여야 합니다.")
        if low > min(opening, close) or high < max(opening, close) or low > high:
            raise ValueError("OHLC 고가·저가 범위가 잘못되었습니다.")
        if i and day <= prices[i - 1][0]:
            raise ValueError("날짜는 중복 없이 오름차순이어야 합니다.")
    trades = []
    entry = 0
    while entry < len(prices):
        entry_day, _, _, _, entry_close = prices[entry]
        target = entry_close * (1 + take_profit / 100)
        stop = entry_close * (1 - stop_loss / 100)
        exit_index = len(prices) - 1
        result = "미청산"
        reason = "기간 종료 시 종가 평가"
        last_price = prices[-1][4]
        for j in range(entry + 1, len(prices)):
            _, opening, high, low, _ = prices[j]
            if opening <= stop:
                result, last_price, reason = "패배", opening, "시가 손절"
            elif opening >= target:
                result, last_price, reason = "승리", opening, "시가 익절"
            elif low <= stop:
                result, last_price = "패배", stop
                reason = "양방향 도달: 손절 우선" if high >= target else "장중 손절"
            elif high >= target:
                result, last_price, reason = "승리", target, "장중 익절"
            else:
                continue
            if result != "미청산":
                exit_index = j
                break
        last_day = prices[exit_index][0]
        trades.append(Trade(entry_day, entry_close, last_day, last_price, result, reason))
        entry = entry + 1 if mode == "daily" else exit_index + 1
    return trades


def summary(trades):
    wins = sum(t.result == "승리" for t in trades)
    losses = sum(t.result == "패배" for t in trades)
    closed = wins + losses
    return {"wins": wins, "losses": losses,
            "open": len(trades) - closed,
            "win_rate": wins / closed * 100 if closed else None,
            "loss_rate": losses / closed * 100 if closed else None}


def split_excluded_period(prices, excluded_start, excluded_end):
    """양 끝 날짜 포함 제외. 제외 구간을 넘어 포지션을 연결하지 않는다."""
    if excluded_start > excluded_end:
        raise ValueError("제외 시작일은 제외 종료일보다 늦을 수 없습니다.")
    before = [row for row in prices if row[0] < excluded_start]
    after = [row for row in prices if row[0] > excluded_end]
    segments = [segment for segment in (before, after) if segment]
    if not segments:
        raise ValueError("제외 후 계산할 거래일이 없습니다.")
    return segments


def calculate_excluding(prices, take_profit, stop_loss, excluded_start, excluded_end):
    trades = []
    for segment in split_excluded_period(prices, excluded_start, excluded_end):
        segment_trades = calculate(segment, take_profit, stop_loss)
        if segment[-1][0] < excluded_start:
            segment_trades = [replace(trade, reason="제외 구간 직전 미청산: 종가 평가")
                              if trade.result == "미청산" else trade for trade in segment_trades]
        trades.extend(segment_trades)
    return trades


def load_prices(symbol, start, end):
    import yfinance as yf
    symbol = symbol.strip().upper()
    now = datetime.now(ZoneInfo("America/New_York"))
    cutoff = now.date() if now.hour >= 18 else now.date() - timedelta(days=1)
    end = min(end, cutoff)
    if start is not None and start > end:
        raise ValueError("해당 기간에 완료된 OHLC 데이터가 없습니다.")
    key = hashlib.sha256(f"ohlc-v1|{symbol}|{start}|{end}".encode()).hexdigest()
    cache_file = CACHE_DIR / f"{key}.json"
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        # 과거 가격 정정도 반영하도록 뉴욕 현지 날짜가 바뀌면 새로 조회한다.
        if cached["saved_date"] == now.date().isoformat():
            prices = [(date.fromisoformat(row[0]), *row[1:]) for row in cached["prices"]]
            if prices:
                calculate(prices, 10, 5)  # 저장된 OHLC 형식 검증
                print("저장된 가격 데이터 사용 (추가 조회 없음).")
                return prices
    except (OSError, ValueError, KeyError, TypeError):
        pass
    kwargs = dict(interval="1d", auto_adjust=False, actions=False,
                  end=(end + timedelta(days=1)).isoformat(), timeout=20)
    if start is None:
        kwargs["period"] = "max"
    else:
        kwargs["start"] = start.isoformat()
    def fetch():
        stock = yf.Ticker(symbol)
        # 최신 버전은 설정으로 예외를 활성화하고, 구버전만 기존 인수를 사용한다.
        debug = getattr(getattr(yf, "config", None), "debug", None)
        if debug is not None and hasattr(debug, "hide_exceptions"):
            previous = debug.hide_exceptions
            try:
                debug.hide_exceptions = False
                history = stock.history(**kwargs)
                metadata = stock.get_history_metadata() if not history.empty else {}
            finally:
                debug.hide_exceptions = previous
        else:
            history = stock.history(**kwargs, raise_errors=True)
            metadata = stock.get_history_metadata() if not history.empty else {}
        return history, metadata

    print("가격 데이터를 조회합니다...", flush=True)
    history, metadata = retry_rate_limit(fetch)
    if history.empty:
        raise ValueError("해당 기간의 가격이 없습니다. 티커·기간 또는 데이터 연결을 확인하세요.")
    exchanges = {"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS"}
    if metadata.get("instrumentType") not in {"EQUITY", "ETF"} or metadata.get("exchangeName") not in exchanges:
        raise ValueError("미국 거래소에 상장된 주식 또는 ETF 티커인지 확인하세요.")
    prices = []
    for stamp, row in history.iterrows():
        day = stamp.date()
        if day > min(end, cutoff) or (start is not None and day < start):
            continue
        values = tuple(float(row[column]) for column in ("Open", "High", "Low", "Close"))
        if not all(isfinite(value) and value > 0 for value in values):
            raise ValueError(f"{day}의 OHLC 데이터가 누락되었거나 잘못되었습니다.")
        prices.append((day, *values))
    if not prices:
        raise ValueError("해당 기간에 완료된 OHLC 데이터가 없습니다.")
    calculate(prices, 10, 5)  # 잘못된 데이터는 저장하지 않는다.
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        payload = {"saved_date": now.date().isoformat(),
                   "prices": [[day.isoformat(), *values] for day, *values in prices]}
        temporary = cache_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(cache_file)
    except OSError:
        print("가격 데이터를 저장하지 못했습니다. 이번 계산은 계속합니다.")
    return prices


def parse_price_date(value):
    value = value.strip()
    normalized = re.sub(r"[년월./]", "-", value).replace("일", "").replace(" ", "").strip("-")
    try:
        parts = normalized.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            return date(*(int(part) for part in parts))
    except ValueError:
        pass
    for pattern in ("%m/%d/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            pass
    raise ValueError(f"지원하지 않는 날짜: {value}. YYYY-MM-DD 또는 MM/DD/YYYY 형식을 사용하세요.")


def parse_price_number(value):
    value = value.strip().replace("\u00a0", "")
    # 영문/한국어 파일의 천 단위 쉼표만 허용한다. 소수 쉼표를 오독하지 않는다.
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", value):
        raise ValueError(f"지원하지 않는 가격: {value}. 소수점은 점(.)이어야 합니다.")
    return float(value.replace(",", ""))


def load_csv_prices(path, symbol, start, end):
    """단일 종목의 일별 OHLC CSV. 거래 결과 CSV와는 다른 입력 형식이다."""
    now = datetime.now(ZoneInfo("America/New_York"))
    cutoff = now.date() if now.hour >= 18 else now.date() - timedelta(days=1)
    prices = []
    raw = Path(path.strip().strip('"')).read_bytes()
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("cp949")
    with io.StringIO(content, newline="") as file:
        reader = csv.DictReader(file)
        headers = {name.strip().lower(): name for name in (reader.fieldnames or [])}
        aliases = {"date": ("날짜", "날짜일"), "open": ("시가",),
                   "high": ("고가",), "low": ("저가",),
                   "close": ("price", "종가", "현재가"), "symbol": ("티커",)}
        for name, alternatives in aliases.items():
            if name not in headers:
                for alternative in alternatives:
                    if alternative in headers:
                        headers[name] = headers[alternative]
                        break
        required = ("date", "open", "high", "low", "close")
        if not all(name in headers for name in required):
            raise ValueError("가격 CSV에는 날짜·시가·고가·저가·종가 열이 필요합니다. Investing.com의 Price는 종가로 읽습니다.")
        for line, row in enumerate(reader, 2):
            try:
                day = parse_price_date(row[headers["date"]])
                if "symbol" in headers and row[headers["symbol"]].strip().upper() != symbol.upper():
                    raise ValueError("입력 티커와 CSV의 Symbol이 다릅니다.")
                if day > min(end, cutoff) or (start is not None and day < start):
                    continue
                values = tuple(parse_price_number(row[headers[name]]) for name in required[1:])
                prices.append((day, *values))
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"가격CSV {line}행 오류: {exc}") from exc
    prices.sort(key=lambda row: row[0])
    if not prices:
        raise ValueError("가격CSV에 해당 기간의 완료된 OHLC 데이터가 없습니다.")
    calculate(prices, 10, 5)
    print("CSV 가격 데이터 사용: 파일에 포함된 기간만 계산합니다.")
    print("CSV의 종목·미국 상장 여부·거래일 누락은 자동 검증할 수 없습니다. 해당 티커의 일별 OHLC인지 확인하세요.")
    return prices


def ask(prompt, parser):
    while True:
        try:
            return parser(input(prompt).strip())
        except ValueError as exc:
            print(f"입력을 확인하세요: {exc}")


def choice(value, options):
    if value not in options:
        raise ValueError(" / ".join(options) + " 중 선택하세요.")
    return value


def positive(value):
    number = float(value)
    if not isfinite(number) or number <= 0:
        raise ValueError("0보다 큰 숫자를 입력하세요.")
    return number


def loss_percent(value):
    number = positive(value)
    if number >= 100:
        raise ValueError("100 미만으로 입력하세요.")
    return number


def choose_price_file():
    """기본 제공 파일 선택 창. Tk가 없는 환경에서는 경로 입력으로 대체한다."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
            return filedialog.askopenfilename(
                parent=root, title="다운로드한 Investing.com 가격 CSV 선택",
                initialdir=str(Path.home() / "Downloads"),
                filetypes=[("CSV 파일", "*.csv"), ("모든 파일", "*.*")],
            )
        finally:
            root.destroy()
    except (ImportError, RuntimeError) as exc:
        print(f"파일 선택 창을 사용할 수 없습니다: {exc}")
    except Exception as exc:
        print(f"파일 선택 창을 열지 못했습니다: {exc}")
    return input("다운로드한 가격 CSV 경로 (Enter: 취소): ").strip()


def select_price_source(symbol, start, end):
    while True:
        print("\n데이터 선택\n1. Yahoo (온라인 조회)\n2. Investing.com (다운로드 후 파일 선택)\n3. 파일 위치 직접 입력\n0. 이번 계산 취소")
        source = ask("데이터 선택 (1/2/3/0): ", lambda s: choice(s, ("1", "2", "3", "0")))
        if source == "0":
            return None
        if source == "1":
            try:
                return load_prices(symbol, start, end)
            except PriceRateLimitError as exc:
                print(exc)
                print("다른 데이터를 선택하거나 0을 눌러 취소하세요.")
                continue
        if source == "2":
            url = "https://www.investing.com/search/?q=" + quote(symbol, safe="")
            print(f"Investing.com 검색: {url}")
            print(f"{symbol}의 미국 상장 종목 → 과거 데이터에서 일별·기간을 선택해 CSV로 다운로드하세요.")
            print("사이트에서 직접 다운로드하는 방식입니다. 자동으로 가격을 수집하지 않습니다.")
            try:
                if not webbrowser.open(url):
                    print("브라우저를 열지 못했습니다. 위 주소에 직접 접속하세요.")
            except webbrowser.Error:
                print("브라우저를 열지 못했습니다. 위 주소에 직접 접속하세요.")
            input("다운로드를 마쳤으면 Enter를 누르세요. 파일 선택 창이 열립니다: ")
            csv_path = choose_price_file()
        else:
            csv_path = input("가격 CSV 파일 위치 입력 (Enter: 데이터 선택으로): ").strip()
        if not csv_path:
            continue
        try:
            return load_csv_prices(csv_path, symbol, start, end)
        except (OSError, ValueError, UnicodeError) as exc:
            print(f"파일을 읽지 못했습니다: {exc}")


def run_once():
    print("미국 상장 주식·ETF OHLC 승률 계산기")
    print("종가 매수 → 다음 거래일부터 OHLC 판정 → 청산 다음 거래일 종가 재진입")
    print("시가가 기준을 넘으면 시가 청산, 장중 양방향 도달 시 손절 우선")
    symbol = input("주식·ETF 티커 (예: AAPL, SPY, QQQ): ").strip().upper()
    take_profit = ask("익절률 (%, 예: 10): ", positive)
    stop_loss = ask("손절률 (%, 예: 5): ", loss_percent)
    print("1. 시작일 ~ 종료일\n2. 시작일 ~ 현재\n3. 상장일부터 ~ 현재 (제공되는 전체 이력)\n4. 전체 기간에서 지정 기간 제외")
    period = ask("기간 선택 (1/2/3/4): ", lambda s: choice(s, ("1", "2", "3", "4")))
    start = ask("시작일 (YYYY-MM-DD): ", date.fromisoformat) if period in ("1", "2") else None
    today = datetime.now(ZoneInfo("America/New_York")).date()
    end = ask("종료일 (YYYY-MM-DD): ", date.fromisoformat) if period == "1" else today
    if end > today or (start is not None and start > end):
        raise ValueError("시작일 ≤ 종료일 ≤ 미국 현지 오늘이어야 합니다.")
    excluded_start = excluded_end = None
    if period == "4":
        excluded_start = ask("제외 시작일 (YYYY-MM-DD): ", date.fromisoformat)
        excluded_end = ask("제외 종료일 (YYYY-MM-DD): ", date.fromisoformat)
        if excluded_start > excluded_end or excluded_end > today:
            raise ValueError("제외 시작일 ≤ 제외 종료일 ≤ 미국 현지 오늘이어야 합니다.")
        print("제외 시작일·종료일 포함. 구간 직전 미청산은 승패에서 제외하고, 구간 이후 새로 진입합니다.")
    prices = select_price_source(symbol, start, end)
    if prices is None:
        return
    if period == "4":
        segments = split_excluded_period(prices, excluded_start, excluded_end)
        trades = calculate_excluding(prices, take_profit, stop_loss, excluded_start, excluded_end)
    else:
        segments = [prices]
        trades = calculate(prices, take_profit, stop_loss)
    stats = summary(trades)
    print(f"\n{symbol} | 실제 계산 기간:")
    for segment in segments:
        print(f"  {segment[0][0]} ~ {segment[-1][0]} ({len(segment)}거래일)")
    if period == "4":
        print(f"제외 기간: {excluded_start} ~ {excluded_end} (양 끝 날짜 포함)")
    if start is None:
        print("전체 제공 이력 기준입니다. 최초 데이터일이 실제 상장일과 다를 수 있습니다.")
    print(f"총 승리수: {stats['wins']} | 총 패배수: {stats['losses']} | 미청산: {stats['open']}")
    ambiguous = sum(t.reason == "양방향 도달: 손절 우선" for t in trades)
    print(f"익절·손절 동시 도달로 손절 우선 처리한 거래: {ambiguous}건")
    if stats["win_rate"] is None:
        print("총 승률·패율: 계산 불가 (청산된 거래 없음)")
    else:
        print(f"총 승률: {stats['win_rate']:.2f}% | 총 패율: {stats['loss_rate']:.2f}%")
    print("승률·패율의 분모는 승리수 + 패배수입니다. 미청산은 제외합니다.")
    output = input("거래 내역 CSV 저장 경로 (Enter: 저장 안 함): ").strip()
    if output:
        with open(output, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["매수일", "매수종가", "청산일 또는 최종관측일", "청산가격 또는 평가종가", "결과", "수익률(%)", "판정 사유"])
            for trade in trades:
                writer.writerow([trade.entry_date, trade.entry_close, trade.last_date,
                                 trade.last_price, trade.result, round(trade.return_pct, 6), trade.reason])
        print(f"저장 완료: {output}")


def main():
    while True:
        try:
            run_once()
        except Exception as exc:
            print(f"오류: {exc}")
        again = ask(
            "\n계속 계산하려면 Enter 또는 1, 종료하려면 0: ",
            lambda value: choice(value or "1", ("1", "0")),
        )
        if again == "0":
            print("계산기를 종료합니다.")
            return
        print()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n입력을 종료했습니다.")
    except Exception as exc:
        print(f"오류: {exc}")
        raise SystemExit(1)
