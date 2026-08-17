# MEDIA RELAY — Bot Telegram avec panneau administrateur

Le bot copie les médias de plusieurs groupes sources vers plusieurs groupes
cibles. Lorsqu'il rejoint un groupe, il affiche automatiquement une interface
à boutons permettant à un administrateur de choisir **Source** ou **Cible**.
Le rôle peut être modifié plus tard depuis le même panneau.

Le tableau de bord affiche les groupes connectés, le nombre de médias détectés,
les copies réussies, les échecs et le taux de réussite. Les photos, vidéos,
albums, GIF, documents, audios, vocaux, notes vidéo et stickers sont gérés.

## Installation

1. Créez le bot avec `@BotFather`.
2. Dans `@BotFather`, lancez `/setprivacy` puis choisissez **Disable**.
3. Copiez `.env.example` vers `.env` et renseignez `BOT_TOKEN`.
4. Lancez `docker compose up -d --build`.
5. Ajoutez le bot comme administrateur dans les groupes. Il doit pouvoir envoyer
   des médias dans les groupes cibles.

Le panneau apparaît automatiquement. `/panel` sert uniquement à le rouvrir si
son message a été supprimé ; toute la configuration se fait avec les boutons.

La configuration et les statistiques sont conservées dans `data/relay.db`.
Seuls les nouveaux médias sont traités. Telegram ne permet pas au bot de
récupérer l'historique antérieur à son arrivée.
