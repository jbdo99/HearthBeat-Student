import datetime
import imgkit
import discord
from discord.ext import commands, tasks
import asyncpg
import typing
import json
import io
import humanize
import os
humanize.i18n.activate("fr_FR")

HTML_TEMPLATE = """
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
<link href="https://cdnjs.cloudflare.com/ajax/libs/materialize/1.0.0/css/materialize.min.css" rel="stylesheet" />
<link href="https://cdnjs.cloudflare.com/ajax/libs/material-design-icons/3.0.1/iconfont/material-icons.min.css" rel="stylesheet" />
<table class="striped">
        <thead>
          <tr>
              <th>Nom/Prénom</th>
              {head}
          </tr>
        </thead>

        <tbody>
             {body}     
        </tbody>
      </table>"""


def is_admin():
    async def predicate(ctx):
        return bool((int(ctx.author.permissions) >> 3) & 1)
    return commands.check(predicate)


class HearthBeat(commands.Cog):
    def __init__(self, bot, host, database, username, password):
        self.bot = bot
        self.host = host
        self.username = username
        self.password = password
        self.database = database
        self.connector = None


    async def init(self):
        """"
        Init the Postgres connector
        :return: None
        """
        self.connector = await asyncpg.connect(user=self.username, password=self.password,
                                          database=self.database, host=self.host)

    async def get_info(self, guild_id, user_id):
        """

        :param guild_id:
        :param user_id:
        :return: dict
        """
        appels = await self.connector.fetch('SELECT * FROM appel WHERE guild=$1', str(guild_id))
        data = {}
        for appel in appels:
            if not appel['name'] in data:
                data[appel['name']] = {'total': 0, 'present': []}
            data[appel['name']]['total'] += 1
            if int(user_id) in json.loads(appel['present']):
                data[appel['name']]['present'].append(
                    f"{appel['name']}, {humanize.naturaldate(appel['date'])} dans {appel['channel']}")
        return data

    async def generate_appel(self, guild, matiere, role):
        await guild.chunk()
        data = {}
        for member in role.members:  # Pour chaque eleve avec le role
            if member.nick is None:  # Si il n  pas de surnom pour le serv
                name = member.name
            else:
                name = member.nick
            if len(name.split(" ")) == 2:
                name = " ".join(name.split(" ")[::-1])
            data[member.id] = {'name': name, 'data': []}  # le nom de l'eleve en key pour le tri et son id en value
        appels = await self.connector.fetch('SELECT * FROM appel WHERE guild=$1', str(guild.id))
        for appel in appels:
            if matiere == "All" or appel['name'] == matiere:
                date = appel['date']  # date du cours
                present = json.loads(appel['present'])
                for i in data.keys():
                    data[i]['data'].append((f"{appel['name']}_{date.day}_{date.month}", i in present))
        return data


    @commands.command(pass_context=True, no_pm=True)
    async def appel(self, ctx, *, name: str):
        """Fait l'appel, syntaxe : `?appel *matiere*`"""
        if ctx.author.voice is not None:
            voice_channel = ctx.author.voice.channel
            present = [k for k in voice_channel.voice_states.keys()]
            appel = {
                'name': name,
                'date': datetime.datetime.now(),
                'present': json.dumps(present),
                'channel': voice_channel.name,
                'guild': str(ctx.guild.id)
            }
            await self.connector.execute(
                'INSERT INTO appel(name, date, present, channel, guild) VALUES ($1, $2, $3, $4, $5);',
                *appel.values())
            await ctx.send(
                f"Ajout de l'appel à la base de données, `{len(present)}` participants le `{appel['date']}` dans `{appel['channel']}`")
        else:
            await ctx.send("Il faut se connecter à un vocal")

    @commands.command(pass_context=True, no_pm=True)
    async def present(self, ctx, role: discord.Role, *, matiere: typing.Optional[str] = 'All'):
        await ctx.send(f":gear: WIP : Lien pour acceder à l'appel : https://hearthbeatstudent.tk/appel/{ctx.guild.id}/{matiere}/{role.id} :floppy_disk:")

    @commands.command(pass_context=True, no_pm=True)
    async def classe(self, ctx, role: discord.Role, *, matiere: typing.Optional[str] = 'All'):
        """Affiche un tableau avec les présence (en mieux)"""
        msg = await ctx.send(":gear: Start to process data :floppy_disk:")
        appel_dic = {}  # Dico avec les appels, et les présents
        eleve_dic = {}  # dico index sur le nom pour le tri alphabétique qui contient l'id
        appels = await self.connector.fetch('SELECT * FROM appel WHERE guild=$1', str(ctx.guild.id))
        for appel in appels:
            print("nom", appel['name'])
            if matiere == "All" or appel['name'] in matiere.split(" "):
                date = appel['date']  # date du cours
                present = json.loads(appel['present'])
                appel_dic[f"{appel['name']} du {date.day}/{date.month}, {date.hour}:{date.minute}"] = present
                # Ajout avec comme index le str d affichage et en value la liste des présents

        await ctx.guild.chunk()
        for member in role.members:  # Pour chaque eleve avec le role
            if member.nick is None:  # Si il n  pas de surnom pour le serv
                name = member.name
            else:
                name = member.nick
            if len(name.split(" ")) == 2:
                name = " ".join(name.split(" ")[::-1])
            eleve_dic[name] = member.id  # le nom de l'eleve en key pour le tri et son id en value
        print(eleve_dic)
        head_str = "".join([f"<th>{appel}</th>" for appel in appel_dic.keys()])  # tete du tableau
        body_str = ""
        elevecount = 0
        elevecount2 = 0
        elevetotal = len(eleve_dic.keys())
        for nom in sorted(eleve_dic):
            elevecount += 1
            elevecount2 += 1
            elv_id = eleve_dic[nom]  # on prend l'id de l eleve
            base = f"<tr><td>{nom}</td>"  # premiere colonne nom
            for cours, present in appel_dic.items():
                if elv_id in present:  # Il est present
                    base += """
                        <td class="center">
                            <i class="material-icons green-text">check_box</i>
                        </td>
                        """
                else:  # Il n'est pas present
                    base += """
                        <td class="center">
                            <i class="material-icons red-text">indeterminate_check_box</i>
                        </td>
                    """
            body_str += base + "</tr>"  # on ferme les balises

            if elevecount > 5 or elevetotal == elevecount2:
                if os.name == "nt":
                    img = imgkit.from_string(HTML_TEMPLATE.format(head=head_str, body=body_str), False, options={"zoom": 2.4})
                elif os.name == "posix":
                    img = imgkit.from_string(HTML_TEMPLATE.format(head=head_str, body=body_str), False,
                                             options={"xvfb": "", "zoom": 2.4, 'quiet': ''})
                else:
                    await ctx.send("Systeme non reconnu")
                await msg.edit(content=":gear:Send Image :arrow_up:")
                picture = discord.File(io.BytesIO(img), filename="heathbeat.jpg")
                await ctx.send(file=picture)
                elevecount = 0
                body_str = ""
        await msg.delete()
        msg = await ctx.send(f":gear: WIP : Lien pour acceder a la classe : https://hearthbeatstudent.tk/users/{ctx.guild.id} :floppy_disk:")
