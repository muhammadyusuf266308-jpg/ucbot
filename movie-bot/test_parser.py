import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from channel_parser import parse_post

test_post = """🎬 Nomi: Spartak: Arena xudolari (barcha qismi)
🇺🇿 Tili: O'zbek tilida
📺 Sifati: 1080p
📅 Yili: 2011
🇺🇸 Davlat: AQSH
⭐ Reyting: IMDb: 8.5 KinoPoisk: 8.3

Kod:237

🤖 Botimiz: @UzKinoMov1eBot
📢 Kanalimiz: https://t.me/UzKinoMoviie"""

result = parse_post(test_post, message_id=1872)
if result:
    print("OK - MUVAFFAQIYAT!")
    print(f"  Nomi    : {result['title']}")
    print(f"  Yili    : {result['year']}")
    print(f"  Tili    : {result['genre']}")
    print(f"  Tavsif  :\n{result['description']}")
    print(f"  Bot kodi: {result['bot_code']}")
    print(f"  Msg ID  : {result['channel_msg_id']}")
else:
    print("XATO - None qaytdi!")
