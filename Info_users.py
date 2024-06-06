# -*- encoding: utf-8 -*-
import ovh
import datetime
import csv
import sys, os
from os import listdir
import configparser
import traceback

#Lecture du fichier de configuration
config = configparser.ConfigParser()
config.sections()
config.read('scripts_conf.ini')

#Chemin du fichier csv de sortie (exploité par Power BI)
csv_output=config['csv_output']['Info_users']
csv_logs=config['csv_output']['Logs_users']
sursis=datetime.timedelta(days=int(config['durations']['MFA_days_sursis']))
activity=datetime.timedelta(days=int(config['durations']['days_activity']))


#Récupération de la liste des utilisateurs
def fetch_users(ovh_account, client,logging):
    users_list=client.get('/me/identity/user')

    #Ajout du compte root à la liste des utilisateurs
    users_list.append(ovh_account)
    return users_list

#Récupération des info de connexion : nom, MFA, date de dernière co
def fetch_log_info(ovh_account, user_list, audit,logging):
    user_log_list=[]
    for log in audit :
        if log['type']=='LOGIN_SUCCESS':
            #le compte racine apparaît avec le nom "None" dans les logs (déjà traité lors de l'historisation des logs normalement)
            if log['authDetails']['userDetails']['user'] is None:
                log['authDetails']['userDetails']['user'] = ovh_account
            user={}
            #audit est une liste de dictionnaires imbriqués
            #Parcours des logs et récupération de chaque compte ayant effectué une connexion et le MFA utilisé
            user['name'] = str(log['authDetails']['userDetails']['user'])
            user['mfa'] = str(log['loginSuccessDetails']['mfaType'])
            user['last_log'] = log['createdAt']
            if user['name'] in user_list:
                #Si le user a déjà été ajouté dans le liste on met à jour sa dernière date de connexion et son type de MFA, sinon on l'ajoute
                checked=False
                for us in user_log_list:
                    if us['name']==user['name']:
                        checked=True
                        us['mfa']=user['mfa']
                        us['last_log']=user['last_log']
                if checked == False:
                    user_log_list.append(user)
        else:
            logging.info(["log['type']",log['type'],"not considered"])
    return user_log_list

#Récupération de la liste des utilisateurs en période de sursis MFA
def fetch_sursis(ovh_account, users_list, user_log_list, client,logging):
    #Définition du délais de sursis accepté pour que l'utilisateur se mette en conformité MFA
    duree_sursis=sursis
    for user in user_log_list :
        #On vérifie que l'utilisateur existe toujours, qu'il ne s'agit pas du compte racine et que son MFA n'est pas activé
        #if user['name'] in users_list and (user['name'] != ovh_account) and user['mfa']== 'NONE':
        if user['name'] in users_list and user['mfa'] == 'NONE':
            try:
                identity = client.get('/me/identity/user/'+user['name']) #récupération des détails du compte utilisateur
                #isolation de la date de création et conversion en objet datetime permetant la manipulation
                creation = identity['creation'] 
                creation = datetime.datetime(int(creation[0:4]), int(creation[5:7]), int(creation[8:10]), int(creation[11:13]), int(creation[14:16]))
                age = datetime.datetime.now()-creation
                #vérification de la condition de sursis
                if age < duree_sursis:
                    user['sursis']=True
                else:
                    user['sursis']=False
            except:
                logging.info([user])
        #Si l'utilisateur existe toujours mais qu'il s'agit soit d'un compte racine, soit d'un compte dont le MFA est activé
        #Il n'y a alors plus de sursis
        elif user['name'] in users_list :
            user['sursis']=False
    return user_log_list

#Récupération de la liste des utilisateurs inactif
def is_user_active(audit, user_log_list,logging):
    duree_inactif=activity #Définintion de la durée depuis la dernière connexion pour être considéré inactif
    for user in audit:
        if user['type']=='LOGIN_SUCCESS':
            #Récupération de la dernière date de connexion et formatage de la date
            last_log=user['createdAt']
            last_log=datetime.datetime(int(last_log[0:4]), int(last_log[5:7]), int(last_log[8:10]))
            since_last_log=datetime.datetime.now()-last_log
            #Vérification de la condition d'inactivité
            for us in user_log_list:
                if us['name'] == user['authDetails']['userDetails']['user'] :
                    if since_last_log>duree_inactif:
                        us['actif']=False
                    elif since_last_log<duree_inactif:
                        us['actif']=True
    return user_log_list

#Ajoute les utilisateurs présents sur le compte mais non présents dans les logs (logs glissants sur un mois)
#Vérifie également si le fichier d'historique contient l'état des users non présents dans les derniers logs
def differentiel(user_list, user_log_list, previous_logs,logging):
    for user in user_list:
        check = False
        for uslog in user_log_list :
            if uslog['name']==user:
                check = True
        if check == False:
            for log in previous_logs:
                if log['name']==user:
                    user_log_list.append(log)
                    check=True
        if check==False:
            usAdd={
                'name' : user,
                'mfa' : 'unknown',
                'sursis' : 'unknown',
                'actif' : 'unknown',
                'last_log' : 'unknown'
            }
            user_log_list.append(usAdd)
    return user_log_list

#Récupération de l'adresse mail liée au compte utilisateur
def fetch_email(ovh_account, client, user_list_full,logging):
    for user in user_list_full:
        if user['name']!=ovh_account:
            user['mail']=client.get('/me/identity/user/'+user['name'])['email']
        else :
            user['mail']=client.get('/me')['email']
    return user_list_full

#Lecture des logs de connexion existants
def previous_logs_read(ovh_account,logging):
    csv_path=csv_logs+'/'+ovh_account+'.csv'
    previous_logs=[]
    #On vérifie que le fichier existe avant de le lire
    if os.path.exists(csv_path):
        with open (csv_path, mode='r') as log_file:
            csv_reader=csv.DictReader(log_file)
            line_count=0
            for row in csv_reader:
                if line_count!=0:
                    log={}
                    log=row
                    previous_logs.append(log)
                line_count=line_count+1
    return previous_logs

#Mise à jour des informations de logs des utilisateurs
def update_previous_logs(ovh_account,previous_logs, user_list_full,logging):
    for user in user_list_full:
        already_in_log=False
        for log in previous_logs:
            if log['name']==user['name']:
                already_in_log=True
                log=user
        if already_in_log==False:
            previous_logs.append(user)
    csv_path=csv_logs+'/'+ovh_account+'.csv'
    with open(csv_path, mode='w',encoding="cp1252",errors='replace') as log_file:
        data_writer=csv.writer(log_file, delimiter=',')
        data_writer.writerow(['name', 'mfa', 'sursis', 'actif', 'last_log', 'mail'])
        for log in previous_logs:
            for attribute in ['name', 'mfa', 'sursis', 'actif', 'last_log', 'mail']: 
                if attribute not in log:log[attribute]='unknown'
            data_writer.writerow([log['name'], log['mfa'], log['sursis'], log['actif'], log['last_log'], log['mail']])

#Ecriture des informations récupérées dans un fichier csv
def csv_write(ovh_account, user_list_full,logging):
    with open(csv_output, mode='a',encoding="cp1252",errors='replace') as data_file:
        data_writer=csv.writer(data_file, delimiter=',')
        for user in user_list_full:
            for attribute in ['name', 'mfa', 'sursis', 'actif', 'last_log', 'mail']: 
                if attribute not in user:user[attribute]='unknown'
            data_writer.writerow([ovh_account, user['name'], user['mfa'], user['sursis'], user['actif'], user['last_log'], user['mail']])    

def compute(clients,logging,client_to_file):
    #Suppression de l'ancien contenu du fichier CSV et écriture des titres de colonnes
    with open(csv_output, mode='w',encoding="cp1252",errors='replace') as data_file:
        data_writer=csv.writer(data_file, delimiter=',')
        data_writer.writerow(['Compte OVH', 'Utilisateur', 'Type MFA', 'Sursis MFA', 'Actif', 'Last log', 'Email'])

    #Connexion à l'API OVH pour chaque compte dont on possède le token
    for client in clients:
        file=client_to_file[client]
        try:
            #Récupération de l'ID du compte ovh
            ovh_account=client.get('/me')['nichandle']
            #Récupération de la liste des utilisateurs du compte
            users_list=fetch_users(ovh_account, client,logging)
            #Récupération des logs
            audit=client.get('/me/logs/audit')
            #Récupération des derniers états enregistrés pour les utilisateurs
            previous_logs=previous_logs_read(ovh_account,logging)
            #Analyse des logs récupérés
            user_log_list=fetch_log_info(ovh_account, users_list, audit,logging)
            user_log_list=fetch_sursis(ovh_account, users_list, user_log_list, client,logging)
            user_log_list=is_user_active(audit, user_log_list,logging)
            user_list_full=differentiel(users_list, user_log_list, previous_logs,logging)
            user_list_full=fetch_email(ovh_account, client, user_list_full,logging)
            update_previous_logs(ovh_account,previous_logs, user_list_full,logging)
            csv_write(ovh_account, user_list_full,logging)
        except:
            logging.info([file,"n'a pas accès au point final ","/me"])
            s=traceback.format_exc()
            logging.info(["raise",s])
