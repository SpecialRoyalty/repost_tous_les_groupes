import asyncio, html, logging, os
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, timezone
import asyncpg
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

load_dotenv(); TOKEN=os.getenv("BOT_TOKEN"); DATABASE_URL=os.getenv("DATABASE_URL")
if not TOKEN: raise RuntimeError("BOT_TOKEN absent. Copiez .env.example vers .env.")
if not DATABASE_URL: raise RuntimeError("DATABASE_URL absent. Ajoutez ${{Postgres.DATABASE_URL}} dans Railway.")
try:
    ADMIN_IDS={int(value.strip()) for value in os.getenv("ADMIN_IDS","").split(",") if value.strip()}
except ValueError as exc:
    raise RuntimeError("ADMIN_IDS doit contenir uniquement des IDs numériques séparés par des virgules.") from exc
if not ADMIN_IDS: raise RuntimeError("ADMIN_IDS est obligatoire. Ajoutez au moins votre ID Telegram dans .env.")
router=Router(); MEDIA_FILTER=F.photo|F.video|F.animation|F.document|F.audio|F.voice|F.video_note|F.sticker
album_messages=defaultdict(list); album_tasks={}
db_pool: asyncpg.Pool | None = None

async def init_db():
    global db_pool
    db_pool=await asyncpg.create_pool(DATABASE_URL,min_size=1,max_size=5,command_timeout=30)
    async with db_pool.acquire() as db:
        await db.execute("CREATE TABLE IF NOT EXISTS chats(chat_id BIGINT PRIMARY KEY,title TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN('source','target')),updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        await db.execute("CREATE TABLE IF NOT EXISTS detected_chats(chat_id BIGINT PRIMARY KEY,title TEXT NOT NULL,detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        await db.execute("INSERT INTO detected_chats(chat_id,title) SELECT chat_id,title FROM chats ON CONFLICT(chat_id) DO NOTHING")
        await db.execute("CREATE TABLE IF NOT EXISTS transfer_stats(source_id BIGINT,target_id BIGINT,success_count BIGINT NOT NULL DEFAULT 0,failure_count BIGINT NOT NULL DEFAULT 0,last_transfer TIMESTAMPTZ,PRIMARY KEY(source_id,target_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS source_stats(source_id BIGINT PRIMARY KEY,media_received BIGINT NOT NULL DEFAULT 0)")

async def set_role(cid,title,role):
    await db_pool.execute("INSERT INTO chats(chat_id,title,role) VALUES($1,$2,$3) ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title,role=excluded.role,updated_at=NOW()",cid,title,role)
async def remove_chat(cid):
    async with db_pool.acquire() as db:
        async with db.transaction():
            await db.execute("DELETE FROM chats WHERE chat_id=$1",cid)
            await db.execute("DELETE FROM detected_chats WHERE chat_id=$1",cid)
async def deactivate_chat(cid):
    await db_pool.execute("DELETE FROM chats WHERE chat_id=$1",cid)
async def register_chat(cid,title):
    await db_pool.execute("INSERT INTO detected_chats(chat_id,title) VALUES($1,$2) ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title,detected_at=NOW()",cid,title)
async def detected_list():
    return await db_pool.fetch("SELECT chat_id,title FROM detected_chats ORDER BY title")
async def get_title(cid):
    return await db_pool.fetchval("SELECT title FROM detected_chats WHERE chat_id=$1",cid)
async def get_role(cid):
    return await db_pool.fetchval("SELECT role FROM chats WHERE chat_id=$1",cid)
async def targets():
    return [r["chat_id"] for r in await db_pool.fetch("SELECT chat_id FROM chats WHERE role='target'")]
async def groups_list():
    return await db_pool.fetch("SELECT chat_id,title,role FROM chats ORDER BY role,title")
async def add_received(s,n):
    await db_pool.execute("INSERT INTO source_stats VALUES($1,$2) ON CONFLICT(source_id) DO UPDATE SET media_received=source_stats.media_received+excluded.media_received",s,n)
async def add_delivery(s,t,n,ok):
    good,bad=(n,0) if ok else (0,n)
    await db_pool.execute("INSERT INTO transfer_stats VALUES($1,$2,$3,$4,$5) ON CONFLICT(source_id,target_id) DO UPDATE SET success_count=transfer_stats.success_count+excluded.success_count,failure_count=transfer_stats.failure_count+excluded.failure_count,last_transfer=excluded.last_transfer",s,t,good,bad,datetime.now(timezone.utc))
async def stats():
    q="SELECT (SELECT COUNT(*) FROM chats WHERE role='source'),(SELECT COUNT(*) FROM chats WHERE role='target'),COALESCE((SELECT SUM(media_received) FROM source_stats),0),COALESCE((SELECT SUM(success_count) FROM transfer_stats),0),COALESCE((SELECT SUM(failure_count) FROM transfer_stats),0)"
    return await db_pool.fetchrow(q)

def panel_kb(cid,role):
    return InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text="✅ Source" if role=="source" else "📤 Définir comme source",callback_data=f"role:source:{cid}")],
      [InlineKeyboardButton(text="✅ Cible" if role=="target" else "📥 Définir comme cible",callback_data=f"role:target:{cid}")],
      [InlineKeyboardButton(text="📊 Statistiques",callback_data=f"view:stats:{cid}"),InlineKeyboardButton(text="🗂 Groupes",callback_data=f"view:groups:{cid}")],
      [InlineKeyboardButton(text="⏸ Désactiver",callback_data=f"role:off:{cid}")],
      [InlineKeyboardButton(text="🔄 Actualiser",callback_data=f"view:panel:{cid}")]])
def back_kb(cid): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Retour au panneau",callback_data=f"view:panel:{cid}")]])
async def panel_text(cid,title):
    label={"source":"📤 SOURCE","target":"📥 CIBLE"}.get(await get_role(cid),"⚪ NON CONFIGURÉ")
    return f"<b>⚙️ MEDIA RELAY — ADMIN</b>\n━━━━━━━━━━━━━━━━━━\n<b>Groupe :</b> {html.escape(title)}\n<b>Statut :</b> {label}\n\nChoisissez le rôle du groupe. Il peut être modifié à tout moment."
def is_owner(uid): return uid in ADMIN_IDS
async def notify_owners(bot,title,cid):
    text=(await panel_text(cid,title))+"\n\n🔐 <b>Administration privée</b> — choisissez le rôle de ce groupe."
    for owner_id in ADMIN_IDS:
        try: await bot.send_message(owner_id,text,reply_markup=panel_kb(cid,await get_role(cid)),parse_mode=ParseMode.HTML)
        except Exception as exc:
            logging.warning("Impossible d'envoyer le panneau privé à ADMIN_ID=%s (%s). Cette personne doit d'abord lancer /start.",owner_id,exc)

async def guard(q,cid):
    if not is_owner(q.from_user.id):
        await q.answer("Accès refusé : vous n'êtes pas autorisé.",show_alert=True); return False
    if not q.message or q.message.chat.type!=ChatType.PRIVATE or q.message.chat.id!=q.from_user.id:
        await q.answer("Ce panneau doit être utilisé en privé.",show_alert=True); return False
    if not await get_title(cid):
        await q.answer("Ce groupe n'est plus disponible.",show_alert=True); return False
    return True

@router.my_chat_member()
async def detected(e:ChatMemberUpdated):
    just_promoted=(e.new_chat_member.status==ChatMemberStatus.ADMINISTRATOR and
                   e.old_chat_member.status!=ChatMemberStatus.ADMINISTRATOR)
    if just_promoted:
        cid=e.chat.id; title=e.chat.title or str(cid)
        await register_chat(cid,title)
        await notify_owners(e.bot,title,cid)
    elif e.new_chat_member.status in {ChatMemberStatus.LEFT,ChatMemberStatus.KICKED}: await remove_chat(e.chat.id)

@router.message(CommandStart())
async def start(m:Message):
    if not m.from_user or not is_owner(m.from_user.id):
        if m.chat.type==ChatType.PRIVATE: await m.answer("⛔ Accès non autorisé.")
        return
    if m.chat.type!=ChatType.PRIVATE: return
    rows=await detected_list()
    if not rows:
        return await m.answer("✅ <b>Accès privé activé.</b>\n\nLe panneau arrivera automatiquement ici dès que le bot sera nommé administrateur d'un groupe.",parse_mode=ParseMode.HTML)
    for cid,title in rows:
        await m.bot.send_message(m.from_user.id,await panel_text(cid,title),reply_markup=panel_kb(cid,await get_role(cid)),parse_mode=ParseMode.HTML)

@router.callback_query(F.data.startswith("role:"))
async def role_action(q:CallbackQuery):
    _,role,raw=q.data.split(":",2); cid=int(raw)
    if not await guard(q,cid): return
    if role=="off": await deactivate_chat(cid)
    else: await set_role(cid,await get_title(cid) or str(cid),role)
    await q.answer("Configuration mise à jour.")
    title=await get_title(cid) or str(cid)
    await q.message.edit_text(await panel_text(cid,title),reply_markup=panel_kb(cid,await get_role(cid)),parse_mode=ParseMode.HTML)

@router.callback_query(F.data.startswith("view:"))
async def view_action(q:CallbackQuery):
    _,view,raw=q.data.split(":",2); cid=int(raw)
    if not await guard(q,cid) or not q.message: return
    if view=="panel": text=await panel_text(cid,await get_title(cid) or str(cid)); kb=panel_kb(cid,await get_role(cid))
    elif view=="stats":
        src,tgt,received,sent,failed=await stats(); rate=sent/(sent+failed)*100 if sent+failed else 100
        text=f"<b>📊 STATISTIQUES</b>\n━━━━━━━━━━━━━━━━━━\n📤 Sources actives : <b>{src}</b>\n📥 Cibles actives : <b>{tgt}</b>\n🖼 Médias détectés : <b>{received}</b>\n✅ Copies réussies : <b>{sent}</b>\n❌ Copies échouées : <b>{failed}</b>\n🎯 Réussite : <b>{rate:.1f}%</b>"; kb=back_kb(cid)
    else:
        rows=await groups_list(); sources=[f"• {html.escape(t)}" for _,t,r in rows if r=="source"]; tgts=[f"• {html.escape(t)}" for _,t,r in rows if r=="target"]
        text="<b>🗂 GROUPES CONNECTÉS</b>\n━━━━━━━━━━━━━━━━━━\n<b>📤 Sources</b>\n"+("\n".join(sources) or "• Aucune")+"\n\n<b>📥 Cibles</b>\n"+("\n".join(tgts) or "• Aucune"); kb=back_kb(cid)
    await q.answer(); await q.message.edit_text(text,reply_markup=kb,parse_mode=ParseMode.HTML)

async def retry(action):
    for attempt in range(3):
        try: await action(); return True
        except TelegramRetryAfter as e: await asyncio.sleep(e.retry_after+.2)
        except (TelegramForbiddenError,TelegramBadRequest) as e: logging.warning("Copie refusée: %s",e); return False
        except Exception:
            if attempt==2: logging.exception("Échec copie"); return False
            await asyncio.sleep(1.5*(attempt+1))
    return False
async def copy_single(m):
    await add_received(m.chat.id,1)
    for tid in await targets():
        if tid!=m.chat.id:
            ok=await retry(lambda tid=tid:m.bot.copy_message(chat_id=tid,from_chat_id=m.chat.id,message_id=m.message_id)); await add_delivery(m.chat.id,tid,1,ok)
async def flush_album(key,bot):
    await asyncio.sleep(1); messages=sorted(album_messages.pop(key,[]),key=lambda m:m.message_id); album_tasks.pop(key,None)
    if not messages:return
    sid=messages[0].chat.id; ids=[m.message_id for m in messages]; await add_received(sid,len(ids))
    for tid in await targets():
        if tid!=sid:
            ok=await retry(lambda tid=tid:bot.copy_messages(chat_id=tid,from_chat_id=sid,message_ids=ids)); await add_delivery(sid,tid,len(ids),ok)
@router.message(MEDIA_FILTER)
async def relay(m:Message):
    if await get_role(m.chat.id)!="source": return
    if m.media_group_id:
        key=(m.chat.id,m.media_group_id); album_messages[key].append(m)
        if old:=album_tasks.get(key): old.cancel()
        album_tasks[key]=asyncio.create_task(flush_album(key,m.bot))
    else: await copy_single(m)

async def main():
    logging.basicConfig(level=logging.INFO); await init_db(); bot=Bot(TOKEN)
    await bot.delete_my_commands()
    for cid,title in await detected_list():
        await notify_owners(bot,title,cid)
    dp=Dispatcher(); dp.include_router(router)
    try: await dp.start_polling(bot,allowed_updates=["message","callback_query","my_chat_member"])
    finally:
        for task in list(album_tasks.values()):
            task.cancel()
            with suppress(asyncio.CancelledError): await task
        await bot.session.close()
        if db_pool: await db_pool.close()
if __name__=="__main__": asyncio.run(main())
