import discord
from discord.ext import commands
from discord.utils import get
import asyncio
from datetime import datetime, timedelta
import random
import json
import os
from gtts import gTTS
from flask import Flask
from threading import Thread

# Flask sunucusu (Render için ZORUNLU)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot çalışıyor!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# Bot ayarları
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='.', intents=intents)

# -------------------- AYARLAR --------------------
KAYIT_KANALI = "register-to-server"
KAYIT_YETKILISI_ROLU = "Kayıt Yetkilisi"
BOY_ROLU = "Boy"
LADY_ROLU = "Lady"
KAYITSIZ_ROLU = "Kayıtsız"
SOHBET_KANALI = "sohbet"
SES_KANALI = "V.Confirmed"

# Sesli karşılama ayarları
KARSILAMA_ROLLERI = ["Kayıtsız", "Founder Of Kross"]
KONUSULANLAR = set()

# -------------------- VERİ DEPOLAMA --------------------
VERI_DOSYASI = "kayit_verileri.json"

def veri_yukle():
    if os.path.exists(VERI_DOSYASI):
        with open(VERI_DOSYASI, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"kayitlar": {}, "dogum_gunleri": {}, "davetler": {}}

def veri_kaydet(veri):
    with open(VERI_DOSYASI, 'w', encoding='utf-8') as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)

# -------------------- SESLİ KONUŞMA SİSTEMİ --------------------
async def sesli_soyle(kanal, metin):
    """Belirtilen ses kanalında Türkçe metni AI sesiyle söyler"""
    try:
        # Google TTS ile ses dosyası oluştur
        tts = gTTS(text=metin, lang='tr', slow=False)
        tts.save("konusma.mp3")
        
        # Ses kanalına bağlan
        if kanal.guild.voice_client:
            await kanal.guild.voice_client.move_to(kanal)
        else:
            await kanal.connect()
        
        await asyncio.sleep(0.5)
        
        # Sesi çal
        voice = kanal.guild.voice_client
        if voice and voice.channel == kanal:
            voice.play(discord.FFmpegPCMAudio("konusma.mp3"))
            
            # Ses bitene kadar bekle
            while voice.is_playing():
                await asyncio.sleep(0.1)
            
            await asyncio.sleep(0.5)
            
            # Dosyayı temizle
            if os.path.exists("konusma.mp3"):
                os.remove("konusma.mp3")
                
    except Exception as e:
        print(f"Seslendirme hatası: {e}")

async def karsilama_rol_kontrol(member):
    """Kullanıcının karşılama alması gereken bir rolü var mı kontrol eder"""
    for rol_adi in KARSILAMA_ROLLERI:
        rol = get(member.guild.roles, name=rol_adi)
        if rol and rol in member.roles:
            return True
    return False

# -------------------- SES KANALI YÖNETİMİ --------------------
class SesYoneticisi:
    def __init__(self):
        self.ses_kanalinda = False
        self.ses_kanali = None
    
    async def kanala_katil(self, ctx, kanal_adi):
        """Belirtilen ses kanalına katıl (kullanıcı ses kanalında olmasa bile)"""
        
        kanal = None
        for vc in ctx.guild.voice_channels:
            if vc.name.lower() == kanal_adi.lower():
                kanal = vc
                break
        
        if kanal is None:
            for vc in ctx.guild.voice_channels:
                if kanal_adi.lower() in vc.name.lower():
                    kanal = vc
                    break
        
        if kanal is None:
            await ctx.send(f"❌ **{kanal_adi}** isimli ses kanalı bulunamadı!\nMevcut kanallar: {', '.join([vc.name for vc in ctx.guild.voice_channels])}")
            return False
        
        if ctx.voice_client is not None:
            if ctx.voice_client.channel == kanal:
                await ctx.send(f"✅ Zaten **{kanal.name}** kanalındayım!")
                return True
            await ctx.voice_client.disconnect()
            await asyncio.sleep(0.5)
        
        try:
            await kanal.connect()
            self.ses_kanalinda = True
            self.ses_kanali = kanal
            
            embed = discord.Embed(
                title="🔊 Ses Kanalına Katıldım!",
                description=f"**{kanal.name}** kanalındayım!\nÇıkmamı istersen `.cik` yazman yeterli.",
                color=discord.Color.green()
            )
            embed.add_field(name="🎵 Durum", value="Hazır bekliyorum!", inline=False)
            embed.add_field(name="👥 Kanaldaki Üyeler", value=f"{len(kanal.members)} kişi", inline=True)
            embed.set_footer(text="Sunucu patlasa çıkmam! 💪")
            
            await ctx.send(embed=embed)
            return True
            
        except discord.Forbidden:
            await ctx.send("❌ Ses kanalına katılma yetkim yok! Lütfen bot yetkilerini kontrol edin.")
            return False
        except Exception as e:
            await ctx.send(f"❌ Bir hata oluştu: {e}")
            return False
    
    async def kanaldan_cik(self, ctx):
        """Ses kanalından ayrıl"""
        if ctx.voice_client is None:
            await ctx.send("❌ Zaten bir ses kanalında değilim!")
            return False
        
        try:
            kanal_adi = ctx.voice_client.channel.name
            await ctx.voice_client.disconnect()
            self.ses_kanalinda = False
            self.ses_kanali = None
            
            embed = discord.Embed(
                title="👋 Ses Kanalından Ayrıldım!",
                description=f"**{kanal_adi}** kanalından çıktım.",
                color=discord.Color.orange()
            )
            
            await ctx.send(embed=embed)
            return True
            
        except Exception as e:
            await ctx.send(f"❌ Çıkış sırasında hata: {e}")
            return False

ses_yoneticisi = SesYoneticisi()

# -------------------- SES OLAYLARI: OTOMATİK KARŞILAMA + GERİ DÖNÜŞ --------------------
@bot.event
async def on_voice_state_update(member, before, after):
    """Ses kanalı hareketlerini takip eder"""
    
    # ===== BOTUN KENDİSİ İÇİN: OTOMATİK GERİ DÖNÜŞ =====
    if member.id == bot.user.id:
        if before.channel is not None and after.channel is None:
            if ses_yoneticisi.ses_kanalinda and ses_yoneticisi.ses_kanali:
                print(f"🔄 Bot {before.channel.name} kanalından çıkarıldı, 3 saniye içinde geri dönüyor...")
                await asyncio.sleep(3)
                try:
                    await ses_yoneticisi.ses_kanali.connect()
                    ses_yoneticisi.ses_kanalinda = True
                    print("✅ Bot başarıyla geri döndü!")
                except Exception as e:
                    print(f"❌ Otomatik geri dönüş başarısız: {e}")
                    ses_yoneticisi.ses_kanalinda = False
                    ses_yoneticisi.ses_kanali = None
        elif before.channel != after.channel and after.channel is not None:
            ses_yoneticisi.ses_kanali = after.channel
            print(f"🔄 Bot {after.channel.name} kanalına taşındı!")
        return
    
    # ===== KULLANICILAR İÇİN: OTOMATİK SESLİ KARŞILAMA =====
    # Kullanıcı bir ses kanalına katıldı
    if after.channel and before.channel != after.channel:
        if await karsilama_rol_kontrol(member):
            # Aynı kişiye 5 dakika içinde tekrar konuşma
            if member.id in KONUSULANLAR:
                return
            
            KONUSULANLAR.add(member.id)
            
            # Hangi rol olduğunu kontrol et
            kayitsiz_rolu = get(member.guild.roles, name=KAYITSIZ_ROLU)
            kayitsiz_mi = kayitsiz_rolu and kayitsiz_rolu in member.roles
            
            if kayitsiz_mi:
                karsilama_mesaji = (
                    f"Hoş geldiniz {member.display_name}! "
                    f"Kaydınız henüz yapılmamış. "
                    f"Kayıt işleminizin başlaması için lütfen ses kanalında bekleyin. "
                    f"Kayıt yetkililerimiz en kısa sürede sizinle ilgilenecektir. "
                    f"Bu sırada dilerseniz sohbet kanalından bir kayıt yetkilisini etiketleyerek süreci hızlandırabilirsiniz. "
                    f"Sunucu kurallarını okumayı unutmayın. "
                    f"İyi eğlenceler dileriz!"
                )
            else:
                karsilama_mesaji = (
                    f"Hoş geldiniz Sayın {member.display_name}! "
                    f"Sunucumuza tekrar hoş geldiniz. "
                    f"Keyifli vakit geçirmenizi dileriz. "
                    f"Herhangi bir sorunuz olursa yetkililere danışabilirsiniz."
                )
            
            await sesli_soyle(after.channel, karsilama_mesaji)
            
            # 5 dakika sonra tekrar konuşabilmesi için ID'yi kaldır
            await asyncio.sleep(300)
            KONUSULANLAR.discard(member.id)
    
    # Kullanıcı ses kanalından tamamen ayrıldı
    if before.channel and after.channel is None:
        KONUSULANLAR.discard(member.id)

# -------------------- HOŞ GELDİN MESAJI --------------------
@bot.event
async def on_member_join(member):
    """Sunucuya yeni katılan kişiye hoş geldin mesajı gönderir"""
    
    kayit_kanali = get(member.guild.text_channels, name=KAYIT_KANALI)
    
    if kayit_kanali is None:
        print(f"Uyarı: '{KAYIT_KANALI}' kanalı bulunamadı!")
        return
    
    kayitsiz_rolu = get(member.guild.roles, name=KAYITSIZ_ROLU)
    if kayitsiz_rolu:
        try:
            await member.add_roles(kayitsiz_rolu)
        except discord.Forbidden:
            print(f"Hata: {member.name} kullanıcısına kayıtsız rolü verilemedi!")
    
    veri = veri_yukle()
    try:
        invites_before = bot.invites_cache.get(member.guild.id, [])
        invites_after = await member.guild.invites()
        bot.invites_cache[member.guild.id] = invites_after
        
        for inv in invites_after:
            if inv.uses > 0:
                before_inv = next((i for i in invites_before if i.code == inv.code), None)
                if before_inv and inv.uses > before_inv.uses:
                    davetci_id = str(inv.inviter.id)
                    if davetci_id not in veri["davetler"]:
                        veri["davetler"][davetci_id] = {"isim": inv.inviter.name, "sayi": 0}
                    veri["davetler"][davetci_id]["sayi"] += 1
                    veri_kaydet(veri)
                    break
    except:
        pass
    
    kayit_yetkilisi = get(member.guild.roles, name=KAYIT_YETKILISI_ROLU)
    
    embed = discord.Embed(
        title="🌟 Sunucumuza Yeni Bir Üye Katıldı!",
        description=f"**Kross Sunucumuza Hoş Geldin, {member.mention}!**",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )
    
    embed.add_field(
        name="✨ Hoş Geldin!",
        value="Seninle birlikte artık çok daha güçlüyüz!\nSunucumuza adım attığın için teşekkür ederiz.",
        inline=False
    )
    
    embed.add_field(
        name="📜 Lütfen Dikkat!",
        value="**Lütfen sunucu kurallarımızı dikkatlice okumanı rica ederiz.**\nTopluluğumuzun huzuru için kurallarımıza uyman çok önemli.",
        inline=False
    )
    
    yetkili_mention = kayit_yetkilisi.mention if kayit_yetkilisi else "@KayıtYetkilisi"
    embed.add_field(
        name="🎤 Kayıt İşlemleri",
        value=f"Ayrıca kayıt işlemleri için ses odalarında beklediğin takdirde\n{yetkili_mention} ekibimiz en kısa sürede gelip seninle ilgilenecektir.",
        inline=False
    )
    
    embed.add_field(
        name="💫 Birlikte Büyüyoruz!",
        value="Tekrar hoş geldin! Birlikte büyüyen bir aile olmaya devam ediyoruz.",
        inline=False
    )
    
    embed.add_field(
        name="📊 Sunucu Bilgisi",
        value=f"👥 Toplam Üye: **{member.guild.member_count}**\n📅 Katılım Tarihi: <t:{int(member.joined_at.timestamp())}:R>",
        inline=False
    )
    
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Kross Sunucusu • {member.guild.name}")
    
    await kayit_kanali.send(embed=embed)

# -------------------- BOT HAZIR --------------------
@bot.event
async def on_ready():
    print(f"✅ {bot.user} olarak giriş yapıldı!")
    print(f"📊 Bağlı sunucu: {len(bot.guilds)}")
    print(f"🎙️ Sesli karşılama aktif! Roller: {KARSILAMA_ROLLERI}")
    
    bot.invites_cache = {}
    for guild in bot.guilds:
        try:
            bot.invites_cache[guild.id] = await guild.invites()
        except:
            bot.invites_cache[guild.id] = []
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name=".gir | .yardim"
        ),
        status=discord.Status.online
    )
    
    print("📋 Sunucular:")
    for guild in bot.guilds:
        print(f"   • {guild.name} - {guild.member_count} üye")
    
    bot.loop.create_task(dogum_gunu_kontrol())

async def dogum_gunu_kontrol():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            veri = veri_yukle()
            bugun = datetime.now().strftime("%d-%m")
            for kullanici_id, bilgi in veri["dogum_gunleri"].items():
                if bilgi.get("tarih") == bugun:
                    for guild in bot.guilds:
                        member = guild.get_member(int(kullanici_id))
                        if member:
                            kanal = get(guild.text_channels, name=SOHBET_KANALI)
                            if kanal:
                                yas = datetime.now().year - bilgi.get("yil", 2000)
                                await kanal.send(
                                    f"🎂 **Doğum Günü Kutlaması!** 🎉\n"
                                    f"{member.mention} bugün **{yas}** yaşına girdi!\n"
                                    f"Herkese iyi eğlenceler! 🎊🎈"
                                )
        except:
            pass
        await asyncio.sleep(86400)

# -------------------- YARDIMCI FONKSİYONLAR --------------------
async def kayit_mesaji_gonder(ctx, member, kayit_eden, verilen_rol):
    """Başarılı kayıt sonrası detaylı mesaj gönderir"""
    
    veri = veri_yukle()
    kayit_eden_id = str(kayit_eden.id)
    
    if kayit_eden_id not in veri["kayitlar"]:
        veri["kayitlar"][kayit_eden_id] = {
            "isim": kayit_eden.name,
            "toplam": 0,
            "erkek": 0,
            "kiz": 0,
            "son_kayit": None
        }
    
    veri["kayitlar"][kayit_eden_id]["toplam"] += 1
    if verilen_rol == BOY_ROLU:
        veri["kayitlar"][kayit_eden_id]["erkek"] += 1
    else:
        veri["kayitlar"][kayit_eden_id]["kiz"] += 1
    
    veri["kayitlar"][kayit_eden_id]["son_kayit"] = datetime.now().isoformat()
    veri_kaydet(veri)
    
    embed = discord.Embed(
        title="✅ Kayıt İşlemi Başarılı!",
        color=discord.Color.green(),
        timestamp=datetime.now()
    )
    
    embed.add_field(
        name="📋 Kayıt Olan Kişi",
        value=f"{member.mention}\n**Kullanıcı Adı:** {member.name}\n**ID:** {member.id}",
        inline=False
    )
    
    embed.add_field(
        name="👤 Kayıt Eden Yetkili",
        value=f"{kayit_eden.mention}\n**Yetkili Adı:** {kayit_eden.name}",
        inline=False
    )
    
    embed.add_field(
        name="🎭 Verilen Rol",
        value=f"**{verilen_rol}**",
        inline=True
    )
    
    embed.add_field(
        name="📅 Kayıt Tarihi",
        value=f"<t:{int(datetime.now().timestamp())}:F>",
        inline=True
    )
    
    toplam_kayit = veri["kayitlar"][str(kayit_eden.id)]["toplam"]
    rozet = ""
    if toplam_kayit >= 100:
        rozet = "👑 Efsane Kayıtçı"
    elif toplam_kayit >= 50:
        rozet = "💎 Profesyonel Kayıtçı"
    elif toplam_kayit >= 10:
        rozet = "⭐ Deneyimli Kayıtçı"
    
    if rozet:
        embed.add_field(name="🏆 Kayıt Rozeti", value=f"**{rozet}** ({toplam_kayit} kayıt)", inline=False)
    
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Kross Sunucusu • Toplam Üye: {ctx.guild.member_count}")
    
    duz_mesaj = (
        f"{member.mention} başarıyla kayıt edildi.\n\n"
        f"**Kayıt Eden Yetkili:**\n"
        f"{kayit_eden.mention}\n\n"
        f"Bu kişinin kayıt işlemi başarılı şekilde tamamlandı ve gerekli roller eksiksiz olarak verildi."
    )
    
    await ctx.send(duz_mesaj)
    await ctx.send(embed=embed)
    
    sohbet_kanali = get(ctx.guild.text_channels, name=SOHBET_KANALI)
    if sohbet_kanali:
        await asyncio.sleep(1)
        await ctx.send(f"💬 {member.mention}, kaydın tamamlandı! {sohbet_kanali.mention} kanalına geçip sohbete katılabilirsin!")
    
    # Kayıt sonrası sesli tebrik
    if ctx.author.voice:
        tebrik_mesaji = f"Tebrikler! {member.display_name} isimli üyemizin kaydı başarıyla tamamlandı. Aramıza hoş geldin!"
        await sesli_soyle(ctx.author.voice.channel, tebrik_mesaji)

# -------------------- KOMUTLAR --------------------

# --- SES KOMUTLARI ---
@bot.command(name='gir')
@commands.has_permissions(manage_channels=True)
async def ses_kanalina_gir(ctx, *, kanal_adi: str = None):
    if kanal_adi is None:
        kanal_adi = SES_KANALI
    await ses_yoneticisi.kanala_katil(ctx, kanal_adi)

@bot.command(name='cik')
@commands.has_permissions(manage_channels=True)
async def ses_kanalindan_cik(ctx):
    await ses_yoneticisi.kanaldan_cik(ctx)

@bot.command(name='ses')
async def ses_bilgi(ctx):
    if ctx.voice_client is None:
        embed = discord.Embed(
            title="🔇 Ses Durumu",
            description="Şu anda bir ses kanalında değilim.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    kanal = ctx.voice_client.channel
    
    if hasattr(ctx.voice_client, 'connected_at'):
        sure = datetime.now() - ctx.voice_client.connected_at
        sure_str = str(sure).split('.')[0]
    else:
        sure_str = "Bilinmiyor"
    
    embed = discord.Embed(
        title="🔊 Ses Durumu",
        description=f"Şu anda **{kanal.name}** kanalındayım!",
        color=discord.Color.green()
    )
    embed.add_field(name="⏱️ Bağlantı Süresi", value=sure_str)
    embed.add_field(name="👥 Kanaldaki Üyeler", value=f"{len(kanal.members)} kişi")
    embed.add_field(name="🎵 Durum", value="Aktif ve hazır!")
    await ctx.send(embed=embed)

@bot.command(name='sesli-soyle')
@commands.has_permissions(manage_channels=True)
async def sesli_soyle_komut(ctx, *, metin: str):
    """Yazdığın metni sesli olarak söyler (test için)"""
    if not ctx.author.voice:
        return await ctx.send("❌ Ses kanalında değilsin!")
    
    await ctx.send(f"🎙️ Söyleniyor: *{metin[:100]}*")
    await sesli_soyle(ctx.author.voice.channel, metin)

# --- KAYIT KOMUTLARI ---
@bot.command(name='e')
@commands.has_permissions(manage_roles=True, manage_nicknames=True)
async def erkek_kayit(ctx, member: discord.Member, ad, yas):
    boy_rolu = get(ctx.guild.roles, name=BOY_ROLU)
    if not boy_rolu:
        await ctx.send(f"❌ '{BOY_ROLU}' rolü bulunamadı!")
        return
    kayitsiz_rolu = get(ctx.guild.roles, name=KAYITSIZ_ROLU)
    if ctx.author.top_role <= member.top_role and ctx.author != ctx.guild.owner:
        await ctx.send("❌ Bu kullanıcıyı kayıt edemezsiniz!")
        return
    try:
        await member.edit(nick=f"{ad} | {yas}")
    except:
        await ctx.send("❌ İsim değiştirme yetkim yok!")
        return
    try:
        await member.add_roles(boy_rolu)
        if kayitsiz_rolu:
            await member.remove_roles(kayitsiz_rolu)
    except:
        await member.edit(nick=None)
        await ctx.send("❌ Rol verme yetkim yok!")
        return
    veri = veri_yukle()
    try:
        dogum_yili = datetime.now().year - int(yas)
        veri["dogum_gunleri"][str(member.id)] = {"isim": member.name, "yil": dogum_yili, "tarih": f"{random.randint(1,28):02d}-{random.randint(1,12):02d}"}
        veri_kaydet(veri)
    except:
        pass
    await kayit_mesaji_gonder(ctx, member, ctx.author, BOY_ROLU)

@bot.command(name='k')
@commands.has_permissions(manage_roles=True, manage_nicknames=True)
async def kiz_kayit(ctx, member: discord.Member, ad, yas):
    lady_rolu = get(ctx.guild.roles, name=LADY_ROLU)
    if not lady_rolu:
        await ctx.send(f"❌ '{LADY_ROLU}' rolü bulunamadı!")
        return
    kayitsiz_rolu = get(ctx.guild.roles, name=KAYITSIZ_ROLU)
    if ctx.author.top_role <= member.top_role and ctx.author != ctx.guild.owner:
        await ctx.send("❌ Bu kullanıcıyı kayıt edemezsiniz!")
        return
    try:
        await member.edit(nick=f"{ad} | {yas}")
    except:
        await ctx.send("❌ İsim değiştirme yetkim yok!")
        return
    try:
        await member.add_roles(lady_rolu)
        if kayitsiz_rolu:
            await member.remove_roles(kayitsiz_rolu)
    except:
        await member.edit(nick=None)
        await ctx.send("❌ Rol verme yetkim yok!")
        return
    veri = veri_yukle()
    try:
        dogum_yili = datetime.now().year - int(yas)
        veri["dogum_gunleri"][str(member.id)] = {"isim": member.name, "yil": dogum_yili, "tarih": f"{random.randint(1,28):02d}-{random.randint(1,12):02d}"}
        veri_kaydet(veri)
    except:
        pass
    await kayit_mesaji_gonder(ctx, member, ctx.author, LADY_ROLU)

# --- LİDERLİK ---
@bot.command(name='liderlik')
async def kayit_liderlik(ctx):
    veri = veri_yukle()
    kayitlar = veri.get("kayitlar", {})
    if not kayitlar:
        await ctx.send("📊 Henüz kayıt yok!")
        return
    sirali = sorted(kayitlar.items(), key=lambda x: x[1]["toplam"], reverse=True)
    embed = discord.Embed(
        title="🏆 Kayıt Liderlik Tablosu",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )
    for i, (kullanici_id, bilgi) in enumerate(sirali[:10], 1):
        madalya = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        embed.add_field(
            name=f"{madalya} {bilgi['isim']}",
            value=f"📊 Toplam: **{bilgi['toplam']}** | 👨 Erkek: {bilgi['erkek']} | 👩 Kız: {bilgi['kiz']}",
            inline=False
        )
    embed.set_footer(text=f"Toplam {len(sirali)} yetkili kayıt yapmış")
    await ctx.send(embed=embed)

# --- DOĞUM GÜNÜ ---
@bot.command(name='dogumgunu')
async def dogum_gunu_ekle(ctx, gun: int, ay: int):
    if gun < 1 or gun > 31 or ay < 1 or ay > 12:
        await ctx.send("❌ Geçersiz tarih! Örnek: `.dogumgunu 15 7` (15 Temmuz)")
        return
    veri = veri_yukle()
    veri["dogum_gunleri"][str(ctx.author.id)] = {
        "isim": ctx.author.name,
        "yil": 2000,
        "tarih": f"{gun:02d}-{ay:02d}"
    }
    veri_kaydet(veri)
    await ctx.send(f"✅ {ctx.author.mention}, doğum günün **{gun} {ay}** olarak kaydedildi! 🎂")

@bot.command(name='dogumgunleri')
async def dogum_gunleri_liste(ctx):
    veri = veri_yukle()
    dogum_gunleri = veri.get("dogum_gunleri", {})
    if not dogum_gunleri:
        await ctx.send("📅 Henüz hiç doğum günü kaydedilmemiş!")
        return
    embed = discord.Embed(title="🎂 Kayıtlı Doğum Günleri", color=discord.Color.pink())
    aylar = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
            "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    for kullanici_id, bilgi in dogum_gunleri.items():
        member = ctx.guild.get_member(int(kullanici_id))
        if member:
            gun, ay = bilgi["tarih"].split("-")
            embed.add_field(
                name=member.display_name,
                value=f"📅 {int(gun)} {aylar[int(ay)]}",
                inline=True
            )
    await ctx.send(embed=embed)

# --- İSTATİSTİK ---
@bot.command(name='istatistik')
async def kayit_istatistik(ctx):
    veri = veri_yukle()
    kayitlar = veri.get("kayitlar", {})
    simdi = datetime.now()
    bugun = simdi.date()
    hafta_once = simdi - timedelta(days=7)
    gunluk_toplam = 0
    haftalik_toplam = 0
    for kullanici_id, bilgi in kayitlar.items():
        son_kayit = bilgi.get("son_kayit")
        if son_kayit:
            son_kayit_tarih = datetime.fromisoformat(son_kayit).date()
            if son_kayit_tarih == bugun:
                gunluk_toplam += 1
            if son_kayit_tarih >= hafta_once.date():
                haftalik_toplam += 1
    embed = discord.Embed(
        title="📊 Kayıt İstatistikleri",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    embed.add_field(name="📅 Bugünkü Kayıtlar", value=f"**{gunluk_toplam}**", inline=True)
    embed.add_field(name="📆 Bu Hafta", value=f"**{haftalik_toplam}**", inline=True)
    embed.add_field(name="👥 Toplam Üye", value=f"**{ctx.guild.member_count}**", inline=True)
    await ctx.send(embed=embed)

# --- DAVET ---
@bot.command(name='davetlerim')
async def davetlerim(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author
    veri = veri_yukle()
    davetler = veri.get("davetler", {}).get(str(member.id), {})
    davet_sayisi = davetler.get("sayi", 0)
    embed = discord.Embed(
        title=f"📨 {member.display_name} - Davet Bilgileri",
        color=discord.Color.green()
    )
    embed.add_field(name="👥 Davet Ettiği Kişi", value=f"**{davet_sayisi}**", inline=False)
    if davet_sayisi >= 50:
        rozet = "👑 Davet Kralı"
    elif davet_sayisi >= 25:
        rozet = "⭐ Davet Ustası"
    elif davet_sayisi >= 10:
        rozet = "🎯 Davetçi"
    else:
        rozet = "🌱 Yeni Davetçi"
    embed.add_field(name="🏅 Rozet", value=rozet, inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command(name='davetliderlik')
async def davet_liderlik(ctx):
    veri = veri_yukle()
    davetler = veri.get("davetler", {})
    if not davetler:
        await ctx.send("📊 Henüz hiç davet takip edilmemiş!")
        return
    sirali = sorted(davetler.items(), key=lambda x: x[1]["sayi"], reverse=True)
    embed = discord.Embed(title="📨 Davet Liderlik Tablosu", color=discord.Color.purple())
    for i, (kullanici_id, bilgi) in enumerate(sirali[:10], 1):
        madalya = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        embed.add_field(
            name=f"{madalya} {bilgi['isim']}",
            value=f"👥 **{bilgi['sayi']}** davet",
            inline=False
        )
    await ctx.send(embed=embed)

# --- SOHBET ---
@bot.command(name='sohbet')
async def sohbet_baslat(ctx):
    sorular = [
        "Bugün hava nasıl sizin oralarda? 🌤️",
        "En son hangi filmi izlediniz? 🎬",
        "Hayalinizdeki tatil neresi? 🏖️",
        "Hangi müzik türünü seversiniz? 🎵",
        "En sevdiğiniz yemek ne? 🍕",
        "Sabah insanı mısınız yoksa gece kuşu mu? 🌅",
        "Hiç evcil hayvanınız oldu mu? 🐱",
        "Hangi oyunları oynuyorsunuz? 🎮",
        "Çay mı kahve mi? ☕",
        "En komik anınız neydi? 😂"
    ]
    soru = random.choice(sorular)
    await ctx.send(f"💬 **Sohbet Başlatıcı:** {soru}")

@bot.command(name='muhabbet')
async def muhabbet(ctx, *, konu: str = None):
    if konu is None:
        konular = ["hayat", "aşk", "hayaller", "anılar", "müzik", "film", "spor"]
        konu = random.choice(konular)
    await ctx.send(
        f"🗣️ **Muhabbet Konusu: {konu.upper()}**\n"
        f"{ctx.author.mention} bir muhabbet başlattı! Herkes katılabilir! 🎉"
    )

@bot.command(name='efkar')
async def efkar(ctx):
    oran = random.randint(0, 100)
    if oran < 20:
        durum = "😊 Hiç efkar yok, keyfin yerinde!"
    elif oran < 50:
        durum = "😐 Azıcık efkarlısın"
    elif oran < 80:
        durum = "😔 Epey efkarlısın, bir çay iç!"
    else:
        durum = "😭 Çok efkarlısın, müzik aç hemen!"
    await ctx.send(f"🎭 {ctx.author.mention} efkar seviyen: **%{oran}**\n{durum}")

# --- ROZET ---
@bot.command(name='rozetlerim')
async def rozetlerim(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author
    veri = veri_yukle()
    kayit_bilgi = veri.get("kayitlar", {}).get(str(member.id), {})
    toplam = kayit_bilgi.get("toplam", 0)
    rozetler = []
    if toplam >= 100:
        rozetler.append("👑 Efsane Kayıtçı (100+)")
    if toplam >= 50:
        rozetler.append("💎 Profesyonel Kayıtçı (50+)")
    if toplam >= 25:
        rozetler.append("🌟 Usta Kayıtçı (25+)")
    if toplam >= 10:
        rozetler.append("⭐ Deneyimli Kayıtçı (10+)")
    if toplam >= 1:
        rozetler.append("🌱 Çaylak Kayıtçı (1+)")
    embed = discord.Embed(title=f"🏅 {member.display_name} - Rozetler", color=discord.Color.gold())
    embed.add_field(name="📊 Toplam Kayıt", value=f"**{toplam}**", inline=False)
    if rozetler:
        embed.add_field(name="🏆 Kazanılan Rozetler", value="\n".join(rozetler), inline=False)
    else:
        embed.add_field(name="🏆 Rozetler", value="Henüz rozet kazanılmamış", inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)

# --- YARDIM ---
@bot.command(name='yardim')
async def yardim(ctx):
    embed = discord.Embed(
        title="📋 Kross Kayıt Bot - Komutlar",
        description="Prefix: `.`",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="🔊 **Ses Komutları**",
        value="`.gir` - V.Confirmed kanalına katıl\n`.gir <kanal>` - İstediğin kanala gir\n`.cik` - Ses kanalından çık\n`.ses` - Ses durumunu göster\n`.sesli-soyle <metin>` - Metni sesli söyle",
        inline=False
    )
    embed.add_field(
        name="📝 **Kayıt Komutları**",
        value="`.e @kullanıcı Ad Yaş` - Erkek kaydı\n`.k @kullanıcı Ad Yaş` - Kız kaydı",
        inline=False
    )
    embed.add_field(
        name="🏆 **Liderlik & İstatistik**",
        value="`.liderlik` - Kayıt liderlik tablosu\n`.istatistik` - Kayıt istatistikleri\n`.rozetlerim` - Rozetlerini göster",
        inline=False
    )
    embed.add_field(
        name="🎂 **Doğum Günü**",
        value="`.dogumgunu <gün> <ay>` - Doğum günü ekle\n`.dogumgunleri` - Doğum günü listesi",
        inline=False
    )
    embed.add_field(
        name="📨 **Davet Sistemi**",
        value="`.davetlerim` - Davet bilgilerin\n`.davetliderlik` - Davet liderliği",
        inline=False
    )
    embed.add_field(
        name="💬 **Sohbet Komutları**",
        value="`.sohbet` - Buz kırıcı soru\n`.muhabbet <konu>` - Muhabbet başlat\n`.efkar` - Efkar ölçer",
        inline=False
    )
    embed.add_field(
        name="🎙️ **YENİ! Sesli Karşılama**",
        value="`Kayıtsız` veya `Founder Of Kross` rolüne sahip kişiler ses kanalına katıldığında bot otomatik olarak hoş geldin mesajını sesli söyler!",
        inline=False
    )
    await ctx.send(embed=embed)

# -------------------- HATA YÖNETİMİ --------------------
@erkek_kayit.error
@kiz_kayit.error
async def kayit_hata(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("⚠️ Eksik bilgi! Doğru kullanım: `.e @kullanıcı Ad Yaş` veya `.k @kullanıcı Ad Yaş`")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("⚠️ Kullanıcı bulunamadı!")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Bu komutu kullanmak için yetkiniz yok!")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("⚠️ Geçersiz argüman!")

# -------------------- BAŞLAT --------------------
if __name__ == "__main__":
    Thread(target=run_flask).start()
    
    print("🚀 Kross Kayıt Bot başlatılıyor...")
    print("🎙️ Sesli karşılama sistemi aktif!")
    TOKEN = os.environ.get('DISCORD_TOKEN')
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ DISCORD_TOKEN bulunamadı!")
