# MEDIA RELAY — Bot Telegram avec panneau administrateur

Le bot copie les médias de plusieurs groupes sources vers plusieurs groupes
cibles. Lorsqu'il rejoint un groupe, il affiche automatiquement une interface
à boutons permettant à un administrateur de choisir **Source** ou **Cible**.
Le rôle peut être modifié plus tard depuis le même panneau.

Le tableau de bord affiche les groupes connectés, le nombre de médias détectés,
les copies réussies, les échecs et le taux de réussite. Les photos, vidéos,
albums, GIF, documents, audios, vocaux, notes vidéo et stickers sont gérés.

## Déploiement sur Railway

1. Créez le bot avec `@BotFather`.
2. Dans `@BotFather`, lancez `/setprivacy` puis choisissez **Disable**.
3. Demandez votre identifiant numérique Telegram à `@userinfobot`.
4. Ajoutez un service **PostgreSQL** au projet Railway.
5. Dans les variables du service du bot, configurez exactement :

   ```env
   BOT_TOKEN=votre_token_botfather
   ADMIN_IDS=123456789,987654321
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   ```

   `Postgres` doit correspondre au nom exact de votre service PostgreSQL.
   Railway remplacera la référence par l'adresse privée de la base.
6. Déployez le dépôt ou l'archive avec le `Dockerfile` fourni.
7. Ajoutez le bot comme administrateur dans les groupes. Il doit pouvoir envoyer
   des médias dans les groupes cibles.

Le panneau apparaît automatiquement. `/panel` sert uniquement à le rouvrir si
son message a été supprimé ; toute la configuration se fait avec les boutons.
Seuls les comptes dont l'ID figure dans `ADMIN_IDS` peuvent ouvrir le panneau,
cliquer sur ses boutons, modifier les rôles, voir les groupes ou les statistiques.
Le bot refuse volontairement de démarrer si cette liste blanche est absente.

La configuration et les statistiques sont conservées dans PostgreSQL Railway.
Les tables sont créées automatiquement au premier démarrage. Aucun volume local
n'est nécessaire et les redéploiements ne suppriment pas les données.
Seuls les nouveaux médias sont traités. Telegram ne permet pas au bot de
récupérer l'historique antérieur à son arrivée.
