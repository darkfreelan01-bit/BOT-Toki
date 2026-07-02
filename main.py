import os
import re
import time
import datetime
import asyncio
import logging
import tempfile
import functools
import itertools
import requests
import yt_dlp

import discord
from discord.ext import commands, tasks
from gtts import gTTS
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

import config

# --- 1. ตั้งค่าระบบและ Credentials ---
logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', filemode='w')

key_path = os.path.join(os.path.dirname(__file__), 'toki-key.json')
if os.path.exists(key_path):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path
    genai.configure() 
else:
    genai.configure(api_key=config.API_KEY)

# --- 2. ตัวแปรสถานะระบบ ---
ALLOWED_CHANNELS = {1153145753926115328: 1509816792300912820} 
ADMIN_ID = 1112780936455667748 

guild_tts_status = {}
guild_ai_status = {}
last_bot_use = {}     
last_channel_use = {} 
channel_histories = {}  
music_queues = {}       

# --- 3. ตั้งค่า AI Model (ดึง Prompt จาก config.py) ---
model = genai.GenerativeModel(
    model_name=config.MODEL_NAME,
    system_instruction=config.TOKI_SYSTEM_INSTRUCTION
)

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

# โหลด Opus สำหรับระบบเสียง
try: 
    discord.opus.load_opus('libopus-0.dll')
except Exception as e: 
    logging.warning(f"Opus load warning (Safe to ignore if voice works): {e}")

def simple_embed(text):
    return discord.Embed(description=text, color=0x3498DB)

# --- 4. ระบบ Status และ Music Queue ---
status_messages = itertools.cycle([
    "เล่น Terraria กัน 🎮", 
    "รอคำสั่งเปิดเพลงอยู่ฮะ 🎶", 
    "จิบกาแฟ Cafe Amazon รอนายท่าน ☕",
    "คิดถึงคนติดเกมจังน้าา 💕"
])

@tasks.loop(minutes=3)
async def change_status():
    await bot.change_presence(activity=discord.Game(name=next(status_messages)))

async def play_next_song(guild, channel):
    if guild.id not in music_queues or not music_queues[guild.id]: return
    if not guild.voice_client or guild.voice_client.is_playing(): return
        
    next_song = music_queues[guild.id].pop(0)
    ydl_opts = {'format': 'bestaudio', 'quiet': True, 'no_warnings': True}
    loop = asyncio.get_event_loop()
    
    try:
        info = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(next_song['url'], download=False))
        
        def after_playing(error):
            asyncio.run_coroutine_threadsafe(play_next_song(guild, channel), bot.loop)
            
        guild.voice_client.play(discord.FFmpegPCMAudio(info['url']), after=after_playing)
        await channel.send(embed=simple_embed(f"เพลงถัดไปจัดให้ตามคิวฮะ: **{next_song['title']}** 🎶"))
    except Exception as e:
        logging.exception("Queue Play Error:")
        await channel.send("เจ๊เปิดเพลงถัดไปไม่ได้อ่ะ ขอข้ามไปคิวต่อไปเลยละกันนะ!")
        await play_next_song(guild, channel)

@bot.event
async def on_ready():
    await bot.tree.sync() # บังคับอัปเดตคำสั่ง / ทุกครั้งที่เปิดบอท
    if not change_status.is_running():
        change_status.start()
    print(f"[{bot.user}] พร้อมย้ายสัมภาระและปั่นระบบแล้วฮะ!")

# --- 5. คำสั่ง Slash Commands ทั้งหมด ---
@bot.tree.command(name="help", description="ดูคู่มือคำสั่งทั้งหมดของเจ๊")
async def help_command(i: discord.Interaction):
    embed = discord.Embed(title="📜 คู่มือการใช้งานระบบของ Toki Rosemarie", color=0x3498DB)
    embed.add_field(name="🎵 หมวดหมู่ระบบเสียงและเพลง", value="`/join`, `/leave`, `/play [url]`, `/skip`, `/stop`, `/queue`", inline=False)
    embed.add_field(name="💬 หมวดหมู่แชทและจัดการระบบ", value="`/ai [True/False]`, `/tts [True/False]`, `/clear [จำนวน]`, `/reset`, `/ping`", inline=False)
    embed.set_footer(text="ถ้ามีอะไรพัง ทักฟ้องนายท่านได้เลยนะฮะ ฟุฟุฟุ...")
    await i.response.send_message(embed=embed)

@bot.tree.command(name="reset", description="รีเซ็ตความจำบอท")
async def reset(i: discord.Interaction):
    channel_histories[i.channel.id] = []
    await i.response.send_message(embed=simple_embed("ความจำเจ๊ถูกล้างเรียบร้อย! พร้อมเริ่มต้นใหม่กับคุณเธอแล้วฮะ! ✨"))

@bot.tree.command(name="ai", description="เปิด/ปิด ระบบสมอง AI (ประหยัดโควตา 100%)")
async def toggle_ai(i: discord.Interaction, state: bool):
    guild_ai_status[i.guild.id] = state
    msg = "ตื่นแล้วฮะ! สมองแจ่มใสพร้อมคุยแล้ว ✨" if state else "เจ๊ขอตัวไปนอนพักสมองก่อนนะ Zzz... 💤"
    await i.response.send_message(embed=simple_embed(msg))

@bot.tree.command(name="tts", description="เปิด/ปิด โหมดอ่านข้อความด้วยเสียง")
async def tts(i: discord.Interaction, state: bool):
    guild_tts_status[i.guild.id] = state
    msg = "เปิดปากเจ๊แล้ว! 🎤" if state else "เงียบก็ได้ เป็นใบ้พิมพ์แชทอย่างเดียว! 🤐"
    await i.response.send_message(embed=simple_embed(msg))

@bot.tree.command(name="leave", description="ไล่เจ๊ออกจากห้องเสียง")
async def leave(i: discord.Interaction):
    await i.response.defer()
    if i.guild.voice_client: 
        music_queues[i.guild.id] = [] # ล้างคิวด้วยเวลาโดนไล่
        await i.guild.voice_client.disconnect()
        await i.followup.send(embed=simple_embed("ชิ...ไปก็ได้!"))
    else: 
        await i.followup.send(embed=simple_embed("ยังไม่ได้เข้าห้องเลยนะ! 😒"))

@bot.tree.command(name="join", description="เรียกเจ๊เข้าห้องเสียง")
async def join(i: discord.Interaction):
    await i.response.defer()
    if i.user.voice: 
        await i.user.voice.channel.connect()
        await i.followup.send(embed=simple_embed("มาคุมห้องแล้วนะจ๊ะ!"))
    else: 
        await i.followup.send(embed=simple_embed("นายท่านยังไม่เข้าห้องเสียงเลยนะ! 😒"))

@bot.tree.command(name="clear", description="ล้างแชท (สิทธิ์เฉพาะคนจัดการข้อความได้)")
async def clear(i: discord.Interaction, amount: int):
    # ป้องกันบั๊ก 403 Forbidden
    if not i.channel.permissions_for(i.guild.me).manage_messages:
        return await i.response.send_message("เจ๊ไม่มีสิทธิ์ลบข้อความนะ (ไปตั้งค่า Role ให้จัดการข้อความได้ด้วยฮะ)", ephemeral=True)
    
    await i.response.defer(ephemeral=True)
    await i.channel.purge(limit=amount)
    await i.followup.send(embed=simple_embed(f"ล้างขยะให้ {amount} ข้อความแล้วนะ! ✨"))

@bot.tree.command(name="play", description="เปิดเพลง / เพิ่มเข้าคิว")
async def play(i: discord.Interaction, url: str):
    await i.response.defer()
    if not i.guild.voice_client:
        if i.user.voice:
            await i.user.voice.channel.connect()
        else:
            return await i.followup.send(embed=simple_embed("นายท่านยังไม่ได้เข้าห้องเสียงเลยนะ! 😒"))
            
    ydl_opts = {'format': 'bestaudio', 'quiet': True, 'no_warnings': True}
    loop = asyncio.get_event_loop()
    
    try:
        info = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=False))
        title = info.get('title', 'Unknown Title')
        
        if i.guild.id not in music_queues: music_queues[i.guild.id] = []
        
        if i.guild.voice_client.is_playing():
            music_queues[i.guild.id].append({'url': url, 'title': title})
            await i.followup.send(embed=simple_embed(f"เพิ่มเข้าคิวแล้วฮะ: **{title}** (คิวที่ {len(music_queues[i.guild.id])}) ⏳"))
        else:
            def after_playing(error):
                asyncio.run_coroutine_threadsafe(play_next_song(i.guild, i.channel), bot.loop)
                
            i.guild.voice_client.play(discord.FFmpegPCMAudio(info['url']), after=after_playing)
            await i.followup.send(embed=simple_embed(f"จัดให้แล้ว: **{title}** 🎶"))
    except Exception as e:
        logging.exception("Play Command Error:")
        await i.followup.send(embed=simple_embed("ดึงเพลงมาเปิดไม่สำเร็จอ่ะคุณเธอ URL ปลอมป่ะเนี่ย? 😒"))

@bot.tree.command(name="skip", description="ข้ามเพลง")
async def skip(i: discord.Interaction):
    await i.response.defer()
    if i.guild.voice_client and i.guild.voice_client.is_playing(): 
        i.guild.voice_client.stop()
        await i.followup.send(embed=simple_embed("ข้ามให้แล้วนะ! ⏭️"))
    else: 
        await i.followup.send(embed=simple_embed("ไม่มีเพลงกำลังเล่นอยู่นะจ๊ะ! 😒"))

@bot.tree.command(name="stop", description="หยุดเล่นเพลงและล้างคิวทั้งหมด")
async def stop(i: discord.Interaction):
    await i.response.defer()
    if i.guild.voice_client and i.guild.voice_client.is_playing(): 
        music_queues[i.guild.id] = []
        i.guild.voice_client.stop() 
        await i.followup.send(embed=simple_embed("ปิดเพลงให้แล้วฮะ! เจ๊จะยอมเงียบให้เธอทำงานก็ได้ 🔇"))
    else: 
        await i.followup.send(embed=simple_embed("เจ๊ยังไม่ได้เปิดเพลงอะไรเลยนะ 😒"))

@bot.tree.command(name="queue", description="ดูคิวเพลงที่กำลังรอเล่นอยู่")
async def queue(i: discord.Interaction):
    if i.guild.id not in music_queues or not music_queues[i.guild.id]:
        return await i.response.send_message(embed=simple_embed("ตอนนี้ไม่มีเพลงในคิวเลยฮะคุณเธอ! 텅~"))
    
    q_list = music_queues[i.guild.id]
    q_text = "\n".join([f"{idx+1}. {song['title']}" for idx, song in enumerate(q_list[:10])])
    if len(q_list) > 10:
        q_text += f"\n... และอีก {len(q_list) - 10} เพลง"
        
    await i.response.send_message(embed=discord.Embed(title="🎶 คิวเพลงของเจ๊", description=q_text, color=0x3498DB))

@bot.tree.command(name="ping", description="เช็คว่าเจ๊ยังอยู่ดีไหม (ดูความหน่วง)")
async def ping(i: discord.Interaction):
    await i.response.send_message(embed=simple_embed(f"🏓 ปิงปอง! ความเร็วการตอบสนองของเจ๊อยู่ที่ **{round(bot.latency * 1000)}ms** ฮะ!"))

# --- 6. ระบบสมอง AI และ TTS (on_message) ---
@bot.event
async def on_message(m):
    # ป้องกันการตอบแชนเนลอื่นและตอบตัวเอง
    if m.guild and m.guild.id in ALLOWED_CHANNELS and m.channel.id != ALLOWED_CHANNELS[m.guild.id]: return
    if m.author == bot.user or not bot.user.mentioned_in(m): return
    if not guild_ai_status.get(m.guild.id, True): return
    
    try:
        clean_content = m.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
        if len(clean_content) < 3 and not m.attachments: return

        current_time = time.time()
        
        # จัดการ History คูลดาวน์ (10 นาทีล้าง 1 ที)
        if m.channel.id in last_channel_use and (current_time - last_channel_use[m.channel.id] > 600):
            channel_histories[m.channel.id] = []
        last_channel_use[m.channel.id] = current_time

        # โควต้าแชทคนทั่วไป (ดีเลย์ 30 วินาที)
        if m.author.id in last_bot_use and (current_time - last_bot_use[m.author.id] < 30) and m.author.id != ADMIN_ID:
            return

        if m.channel.id not in channel_histories:
            channel_histories[m.channel.id] = []

        # แท็กระบบแยกแยะคนคุย (ดึงจาก Config Rule 6)
        user_tag = "[คุยกับนายท่าน/ผู้สร้าง]" if m.author.id == ADMIN_ID else "[คุยกับคนทั่วไป]"
        
        # ดึงเวลาปัจจุบันมาใส่ใน Prompt เพื่อให้เจ๊รู้ว่ากี่โมง
        time_now = datetime.datetime.now().strftime("%H:%M")
        prompt_text = f"[{time_now}] {user_tag} {m.author.name}: {clean_content}"

        current_parts = [prompt_text]
        loop = asyncio.get_running_loop()

        # ประมวลผลรูปภาพ
        if m.attachments:
            for att in m.attachments[:1]:
                if att.content_type and att.content_type.startswith("image/"):
                    img_data = await loop.run_in_executor(None, lambda: requests.get(att.url).content)
                    current_parts.append({'mime_type': att.content_type, 'data': img_data})

        full_contents = channel_histories[m.channel.id] + [{"role": "user", "parts": current_parts}]

        # ปลดเซ็นเซอร์
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        response_text = ""
        async with m.channel.typing():
            for attempt in range(3):
                try:
                    # ปรับเพิ่ม max_output_tokens เป็น 1500 เพื่อรับประกันว่าเจ๊จะพ่นแชท MomoTalk ได้จนจบโดยไม่ขาดตอน
                    response_obj = await loop.run_in_executor(
                        None, 
                        functools.partial(
                            model.generate_content, 
                            full_contents, 
                            safety_settings=safety_settings,
                            generation_config={
                                "max_output_tokens": 1500,
                                "temperature": 0.8,
                                "top_p": 0.95
                            } 
                        )
                    )
                    
                    if response_obj.candidates and response_obj.candidates[0].content.parts:
                        response_text = response_obj.text
                        break
                    elif attempt == 2:
                        response_text = "อาร่า~ ตอนนี้เค้าขอตัวไปร่ายเวทย์แป๊บนึงนะ ไว้คุยกันใหม่นะจ๊ะ!"
                    else:
                        await asyncio.sleep(2)
                            
                except Exception as e:
                    logging.warning(f"Generate Attempt {attempt + 1} Failed: {e}")
                    if "PROHIBITED_CONTENT" in str(e):
                        response_text = "เจ๊โดนระบบ Google จับเซ็นเซอร์นิดหน่อยฮะ ขอเปลี่ยนเรื่องคุยแป๊บนึงนะ!"
                        break
                    if attempt == 2: raise e 
                    await asyncio.sleep(2) 

        # บันทึกประวัติ (เพิ่มความจำให้เจ๊ Toki เป็น 20 ข้อความ)
        channel_histories[m.channel.id].append({"role": "user", "parts": [prompt_text]})
        channel_histories[m.channel.id].append({"role": "model", "parts": [response_text]})
        channel_histories[m.channel.id] = channel_histories[m.channel.id][-20:] 
        last_bot_use[m.author.id] = time.time()

        # แยกลำดับการอ่านและการส่งอีโมจิ
        parts = [p.strip() for p in response_text.split('\n') if p.strip()]
        for p in parts:
            # ลบ Discord Custom Emoji ชื่อสั้น ออกก่อนส่งให้ TTS อ่าน เพื่อไม่ให้อ่านขยะ
            clean_text_for_tts = re.sub(r'<a?:\w+:\d+>', '', p)
            clean_text_for_tts = re.sub(r':[\w~]+:', '', clean_text_for_tts)
            
            # ส่งข้อความและแปลงอีโมจิให้เป็นรูป
            for match in re.finditer(r':(A?[\w~]+):', p):
                raw_text = match.group(0)
                e_name = match.group(1).replace('~', '_')
                target_emoji = discord.utils.get(m.guild.emojis, name=e_name)
                # จะทำการแปลงจาก Text (เช่น :AnosHeh:) ให้เป็น Emoji Object เพื่อให้ Discord แสดงผลถูกต้อง
                p = p.replace(raw_text, str(target_emoji) if target_emoji else "")
            
            if p.strip(): await m.channel.send(p.strip())
            
            # ระบบ TTS ป้องกันบั๊ก FFmpeg ค้าง และไม่อ่านแท็กอีโมจิ
            if m.guild.voice_client and guild_tts_status.get(m.guild.id, True):
                if not m.guild.voice_client.is_playing() and clean_text_for_tts.strip():
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                        temp_path = tmp.name
                    
                    tts = gTTS(text=clean_text_for_tts, lang='th')
                    await loop.run_in_executor(None, tts.save, temp_path)
                    
                    def after_playing_tts(error):
                        time.sleep(0.5)
                        try:
                            if os.path.exists(temp_path): os.remove(temp_path)
                        except: pass
                            
                    m.guild.voice_client.play(discord.FFmpegPCMAudio(temp_path), after=after_playing_tts)
            await asyncio.sleep(0.5) 
            
    except Exception as e: 
        logging.exception("Critical Error in on_message:")
        if "429" in str(e) or "quota" in str(e).lower():
            await m.channel.send("โควต้าสมองเจ๊หมดเกลี้ยงแล้วนะฮะ คุณเธอ! 😭 พักให้เจ๊ชาร์จแบตแป๊บนึงเถอะค้าบ~")
        elif "PROHIBITED_CONTENT" in str(e):
            await m.channel.send("เจ๊โดนระบบ Google จับเซ็นเซอร์อ่ะ! ขอเปลี่ยนเรื่องคุยแป๊บนึงนะฮะ 💦")
        else:
            await m.channel.send("เจ๊สะดุดล้มนิดหน่อยคุณเธอ ระบบเอ๋อชั่วคราว ลองเรียกเจ๊ใหม่อีกทีนะฮะ! 😵")

bot.run(config.BOT_TOKEN)