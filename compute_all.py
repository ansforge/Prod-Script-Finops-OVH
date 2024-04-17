# -*- encoding: utf-8 -*-
import ovh
import csv
import sys
import configparser
import json
import time
import datetime
from office365.runtime.auth.authentication_context import AuthenticationContext
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.files.file import File
import glob
import arrow
import os
import pause
import string
import random
import pandas as pd
import calendar
import pickle
import smtplib
import traceback
import logging
from importlib import reload

import Calcul_inducteurs
import Info_users

from Parameters import *

alerts=set()

tz="Europe/Paris"
datetime_format="YYYY-MM-DD-HH-mm-ss"
def ts_to_local_time_str(ts):
	return arrow.get(ts).to(tz).format(datetime_format)
def local_time_str_to_ts(str_date):
  return arrow.get(str_date,datetime_format).replace(tzinfo=tz).timestamp()

Tenant_to_ratio={}
unknown_tenant_ratio=set()

#Lecture du fichier de configuration
config = configparser.ConfigParser()
config.sections()
config.read('scripts_conf.ini')

#Conf de données techniques
GW_region=config['technique']['GW_region']
GW_region=GW_region.split()

csv_output=config['csv_output']['Folder_path']

#Chemin du fichier csv de sortie (exploité par Power BI)
csv_output0=config['csv_output']['Info_billing']
header0=['ID tenant','Instance ID','Type d\'instance',\
'Temps d\'activité (heures)','Prix actuel','Mode de facturation']

csv_output1=config['csv_output']['Info_billing_instance_history']
header1=['Periode','Tenant ID','Instance ID','Temps d\'utilisation (heure)',\
 'Coût','Mode de facturation','Mode de facturation pertinent']

csv_output2=config['csv_output']['Info_billing_managed_public_cloud']
header2=['Periode','Tenant','service','Région','Prix']

csv_output3=config['csv_output']['Info_billing_snapshot']
header3=['Periode','Tenant','Région','Prix']

csv_output4=config['csv_output']['Info_billing_storage']
header4=['Periode','Tenant','Région','Prix']

csv_output5=config['csv_output']['Info_instances']
header5=['Tenant ID','Instance ID','Instance Name','Image OS','Type','IPV4',\
'IPV6','RAM','Disque (Go)','CPU','Bande passante','Region','Status']

csv_output6=config['csv_output']['Info_tenant']
header6=['Nom du service', 'ID du service', 'Type de service', 'HDS', 'SNC',\
'Contact administratif', 'Contact technique', 'Contact facturation']

csv_output7=config['csv_output']['Info_services']
header7=['Tenant ID','Service ID','Service name','Status','Region']

csv_output8=config['csv_output']['Missing_token']
header8=['Missing tokens']

csv_output9=config['csv_output']['Info_usage']
header9=['Nom du service','Datacenter Id','Nom de la VM','Consommation moyenne de RAM','Pic de consommation de RAM','Max de consommation de RAM','Consommation moyenne de CPU','Pic de consommation de CPU','Max de consommation de CPU','jour']

csv_output10=config['csv_output']['Info_date']
header10=['Date Time']

def id_generator(size=16,chars=string.ascii_uppercase+string.digits):
	return ''.join(random.choice(chars) for _ in range(size))

def redressement(price,t):
	if t in Tenant_to_ratio:
		return price*Tenant_to_ratio[t]
	else:
		unknown_tenant_ratio.add(t)
		return price

#Fonction d'écriture des données dans un fichier csv
def csv_write(csv_file,header,liste):
	logging.info(["--->",csv_file])
	file=open(csv_file[:-4]+'.csv','w',encoding="cp1252",errors='replace')
	data_writer=csv.writer(file,delimiter=',')
	data_writer.writerow(header)
	for e in liste:data_writer.writerow([a for a in e])
	file.close()

# Récupération des informations de consommation des instances ce chaque tenant 
# à l'heure actuelle pour Public Cloud
def fetch_public_cloud_instance_current(tenant_dict):
	tenant_instance_list=[]
	for t in tenant_dict:
		client=tenant_dict[t]
		r1=client.get('/cloud/project/'+str(t))
		if r1['status']=='ok':
			# On récupère une liste des info de facturation par instances pour 
			# le tenant complet, toutes les instances sont dans la même liste
			tenant_info=client.get('/cloud/project/'+str(t)+'/usage/current')
			for mode in ['hourlyUsage','monthlyUsage']:
				if mode in tenant_info:
					if tenant_info[mode]!=None:
						for category in tenant_info[mode]['instance']:
							typee=category['reference']
							for instance in category['details']:
								idd=instance['instanceId']
								price=instance['totalPrice']
								price=redressement(price,t)
								# Nous n'avons pas encore trouvé comment récupérer 
								# l'uptime des instance en monthly
								if mode=='hourlyUsage':
									timee=instance['quantity']['value']
								else:
									timee=0
								instance_info=[t,idd,typee,timee,price,mode]
								tenant_instance_list.append(instance_info)
	return tenant_instance_list

#Récupération des informations de facturation de chaque instance
def fetch_history_instance(tenant_dict):
	global_history=[]
	#Les isntances facturées au mois et celles à l'heure sont séparées, on s'assure donc de regarder les deux modes
	billing_mode=['hourlyUsage', 'monthlyUsage']
	for t in tenant_dict:
		client=tenant_dict[t]
		r1=client.get('/cloud/project/'+str(t))
		if r1['status']=='ok':
			tenant_history = client.get('/cloud/project/'+str(t)+'/usage/history')
			for history_entry in tenant_history :
				#On regarde le détail pour chaque entrée
				history_details=client.get('/cloud/project/'+str(t)+'/usage/history/'+str(history_entry['id']))
				for mode in billing_mode: #On balaie les deux modes de facturation
					instance_list= history_details[mode]['instance']
					for category in instance_list:
						for instance in category['details']:
							period=history_details['period']['to'][:10]
							#Afin de vérifier qu'une instance est sur le bon mode de facturation nous devons calculer son ratio de temps
							#passé allumée, nous devons donc calculer le temps d'existance de l'instance sur la période de facturation
							#(soit le temps maximal théorique d'uptime)
							p1=history_details['period']['from']
							p2=history_details['period']['to']
							periode_from=datetime.datetime(int(p1[0:4]),int(p1[5:7]),int(p1[8:10]))
							periode_to=datetime.datetime(int(p2[0:4]),int(p2[5:7]),int(p2[8:10]))
							periode_delta=periode_to-periode_from
							#On calcule ensuite le ratio du temps d'uptime réel par rapport au temps total
							timee= 0
							isBillingModeGood=True
							if(mode == 'hourlyUsage'):timee=instance['quantity']['value']
							activity_ratio=timee/(periode_delta.total_seconds()/3600)
							
							#Si l'instance était up plus de 50% du temps, c'est la facturation au mois qui est la plus adaptée, sinon c'est
							#celle à l'heure
							if (activity_ratio>=0.5 and mode == 'monthlyUsage') or (activity_ratio<0.5 and mode=='hourlyUsage'):
								isBillingModeGood=True
							else:
								isBillingModeGood=False 
							#On récupère les autres informations pertinentes de l'instance
							billingMode=mode
							tenantID=t
							instanceID=instance['instanceId']
							price=instance['totalPrice']
							price=redressement(price,t)
							global_history.append([period,tenantID,instanceID,timee,price,billingMode,isBillingModeGood])
	return global_history

#Récupération des informations de facturation de chaque service managé
def fetch_history_service(tenant_dict):
	global_history=[]
	for t in tenant_dict:
		client=tenant_dict[t]
		r1=client.get('/cloud/project/'+str(t))
		if r1['status']=='ok':
			#On récupère la liste des entrées de facturations
			tenant_history = client.get('/cloud/project/'+str(t)+'/usage/history')
			for history_entry in tenant_history :
				#On regarde le détail pour chaque entrée
				history_details=client.get('/cloud/project/'+str(t)+'/usage/history/'+str(history_entry['id']))
				#On récupère les informations de chaque service
				for service in history_details['resourcesUsage']:
					for location in service['resources']:
						region_price=sum([0]+[i['totalPrice']for i in location['components']])
						period=history_details['period']['to'][:10]
						tenantID=t
						servicee=service['type']
						region=location['region']
						price=region_price
						price=redressement(price,t)
						global_history.append([period,tenantID,servicee,region,price])
	return global_history

#Récupération des informations de facturation de chaque snapshot
def fetch_history_snapshot(tenant_dict):
	global_history=[]
	for t in tenant_dict:
		client=tenant_dict[t]
		r1=client.get('/cloud/project/'+str(t))
		if r1['status']=='ok':
			tenant_history = client.get('/cloud/project/'+str(t)+'/usage/history')
			for history_entry in tenant_history :
				#On regarde le détail pour chaque entrée
				history_details=client.get('/cloud/project/'+str(t)+'/usage/history/'+str(history_entry['id']))
				period=history_details['period']['to'][:10]
				for snapshot in history_details['hourlyUsage']['snapshot']:
					region=snapshot['region']
					price=snapshot['totalPrice']
					price=redressement(price,t)
					global_history.append([period,t,region,price])
	return global_history

#Récupération des informations de facturation de chaque storage
def fetch_history_storage(tenant_dict):
	global_history=[]
	for t in tenant_dict:
		client=tenant_dict[t]
		r1=client.get('/cloud/project/'+str(t))
		if r1['status']=='ok':
			tenant_history = client.get('/cloud/project/'+str(t)+'/usage/history')
			for history_entry in tenant_history :
				#On regarde le détail pour chaque entrée
				history_details=client.get('/cloud/project/'+str(t)+'/usage/history/'+str(history_entry['id']))
				period=history_details['period']['to'][:10]
				for storage in history_details['hourlyUsage']['storage']:
					region=storage['region']
					price=storage['totalPrice']
					price=redressement(price,t)
					global_history.append([period,t,region,price])
	return global_history

#Récupère les informations pour chaque instance
def fetch_public_cloud_instance_info(tenant_dict):
	instance_list=[]
	for t in tenant_dict:
		client=tenant_dict[t]
		r1=client.get('/cloud/project/'+str(t))
		if r1['status']=='ok':
			tenant_instance_list = client.get('/cloud/project/'+str(t)+'/instance')
			for inst in tenant_instance_list:
				inst_details=client.get('/cloud/project/'+str(t)+'/instance/'+str(inst['id']))
				idd=inst_details['id']
				name=inst_details['name']
				ipv4=''
				ipv6=''
				if inst_details['ipAddresses'] :
					ipv4=inst_details['ipAddresses'][0]['ip']
					ipv6=inst_details['ipAddresses'][1]['ip']
				region=inst_details['region']
				status=inst_details['status']
				image='unknown'
				if inst_details['image'] is not None :
					image=inst_details['image']['name']
				Typee=inst_details['flavor']['name']
				RAM=inst_details['flavor']['ram']
				Disk=inst_details['flavor']['disk']
				CPU=inst_details['flavor']['vcpus']
				Bandwidth=inst_details['flavor']['inboundBandwidth']
				instance_list.append([t,idd,name,image,Typee,ipv4,ipv6,RAM,Disk,CPU,Bandwidth,region,status])
	return instance_list

#Récupération des informations sur les instances HPC de la même manière qu'on le fait pour les instances Public Cloud
def fetch_HPC_cloud_instance_info(tenant_dict):
	instance_list=[]
	for t in tenant_dict:
		client=tenant_dict[t]
		r1=client.get('/dedicatedCloud/'+str(t))
		if r1['state']=='delivered':
			datacenter_list=client.get('/dedicatedCloud/'+str(t)+'/datacenter')
			for dc in datacenter_list:
				HPC_instance_list=client.get('/dedicatedCloud/'+str(t)+'/datacenter/'+str(dc)+'/vm')
				for instance in HPC_instance_list:
					# logging.info('/dedicatedCloud/'+str(t)+'/datacenter/'+str(dc)+'/vm/'+str(instance))
					for i in range(5):
						try:
							inst_details =client.get('/dedicatedCloud/'+str(t)+'/datacenter/'+str(dc)+'/vm/'+str(instance))
							idd=inst_details['vmId']
							name=inst_details['name']
							ipv4=inst_details['hostName']
							ipv6=0
							region='unknown'
							status=inst_details['powerState']
							image='unknown'
							if inst_details['cdroms'] and len(inst_details['cdroms'])!=0:
								image=inst_details['cdroms'][0]['iso']
							Typee='NA'
							RAM=inst_details['memoryMax']
							Disk='NA'
							CPU=inst_details['cpuNum']
							Bandwidth='NA'
							instance_list.append([t,idd,name,image,Typee,ipv4,ipv6,RAM,Disk,CPU,Bandwidth,region,status])
							break
						except:
							continue
	return instance_list

#Récupération des informations sur les instances VPS de la même manière qu'on le fait pour les instances Public Cloud
def fetch_VPS_instance_info(tenant_dict):
	instance_list=[]
	for t in tenant_dict:
		client=tenant_dict[t]
		tenant_details = client.get('/vps/'+str(t))
		idd=tenant_details['name']
		name= 'unknown'
		if tenant_details['displayName'] is not None:
			name=tenant_details['displayName']
		ipv4=0
		ipv6=0
		region=tenant_details['zone'].split('-')[1].upper()
		status=tenant_details['state']
		image='unknown'
		Typee=tenant_details['model']['offer']
		RAM=tenant_details['model']['memory']
		Disk=tenant_details['model']['disk']
		CPU=tenant_details['model']['vcore']
		Bandwidth='NA'
		instance_list.append([t,idd,name,image,Typee,ipv4,ipv6,RAM,Disk,CPU,Bandwidth,region,status])
	return instance_list

#Récupération des infos sur les loadbalancers déployés sur les tenants Public Cloud
def fetch_LB_info(client,tid):
	LB_list=[]
	for rg in GW_region:
		try:
			LB_list_tenant=client.get('/cloud/project/'+str(tid)+'/region/'+rg+'/loadbalancing/loadbalancer')
			for LB in LB_list_tenant:
				LB_details=client.get('/cloud/project/'+str(tid)+'/region/'+rg+'/loadbalancing/loadbalancer/'+LB['id'])
				ID=LB['id']
				name=LB['name']
				status=LB['operatingStatus']
				LB_list.append([tid,ID,name,status,rg])
		except:
			logging.info(["exception for fetch_LB_info",tid,rg])
	return LB_list

#Récupération des infos sur les gateways déployées sur les tenants Public Cloud
def fetch_GW_info(client,tid):
	GW_list=[]
	for rg in GW_region:
		try:
			GW_list_tenant=client.get('/cloud/project/'+str(tid)+'/region/'+rg+'/gateway')
			for GW in GW_list_tenant:
				ID=GW['id']
				name=GW['name']
				status=GW['status']
				region=GW['region']
				GW_list.append([tid,ID,name,status,rg])
		except:
			logging.info(["exception for fetch_LB_info",tid,rg])
	return GW_list

#Flag tous les tenant ayant une certification HDS
def check_for_hds(tenant_list):
	name_i=0
	uniqueID_i=1
	hds_i=3
	hds_list=[]
	for tenant in tenant_list:
		name=tenant[name_i]
		if '-certification-hds' in name:hds_list.append(name[:-18])
	for tenant in tenant_list:
		tenant[hds_i]=False
		for hds in hds_list:
			if hds in tenant[uniqueID_i]:
				tenant[hds_i]=True
	return tenant_list

#Flag tous les tenant ayant une certification SecNumCloud (valable uniquement pour HPC)
def check_for_snc(tenant_list):
	name_i=0
	uniqueID_i=1
	hds_i=3
	snc_i=4
	snc_list=[]
	for tenant in tenant_list:
		name=tenant[name_i]
		if '/option/snc' in name:snc_list.append(name[:-11])
	for tenant in tenant_list:
		tenant[snc_i]=False
		for snc in snc_list:
			if snc in tenant[uniqueID_i]:
				tenant[snc_i]=True
				tenant[hds_i]=True
	return tenant_list

#Récupération des informations pour chacun des tenants du compte
def fetch_tenant_info(tenant_id_dict):
	tenant_list=[]
	GW_list_global=[]
	LB_list_global=[]
	hds=False
	snc=False
	for tid in tenant_id_dict:
		client=tenant_id_dict[tid]
		#Appel de l'API retournant les détails par tenant
		tenant_info=client.get('/services/'+str(tid)) 
		name=tenant_info['resource']['displayName']
		uniqueID=tenant_info['resource']['name']
		if tenant_info['billing']['lifecycle']['current']['state'] in ['active','toRenew']:
			productType=tenant_info['resource']['product']['description']
			#Récupération des 3 contacts pour chaque tenant
			contact_admin=''
			contact_tech=''
			contact_bill=''
			for ct in tenant_info['customer']['contacts']:
				code=ct['customerCode']
				if ct['type']=="administrator":contact_admin=code
				elif ct['type']=="technical":contact_tech=code
				elif ct['type']=="billing":contact_bill=code
			if productType=='Public Cloud Project':
				LB_list_global.extend(fetch_LB_info(client,uniqueID))
				GW_list_global.extend(fetch_GW_info(client,uniqueID))
			tenant_list.append([name,uniqueID,productType,hds,snc,contact_admin,contact_tech,contact_bill])
	tenant_list=check_for_hds(tenant_list)
	tenant_list=check_for_snc(tenant_list)
	return tenant_list, GW_list_global+LB_list_global

#Detection des comptes présents comme contact mais dont on ne possède pas les tokens
def detect_missing_token(nich_set,tenant_list):
	contact_admin_i=5
	contact_tech_i=6
	missing_set=set()
	for tenant in tenant_list:
		contact=tenant[contact_admin_i]
		if contact not in nich_set | missing_set:
			missing_set.add(contact)
		contact=tenant[contact_tech_i]
		if contact not in nich_set | missing_set:
			missing_set.add(contact)
	return [[a] for a in missing_set]

def fetch_dedicatedCloud_cpu_ram(tenant_dict):
	tt1=ts_to_local_time_str(time.time())
	tt2=tt1[:10]
	try:
		with open('dedicatedCloud_saved_dictionary.pkl','rb') as f:
			dedicatedCloud=pickle.load(f)
	except:None
	for t in tenant_dict:
		client=tenant_dict[t]
		r1=client.get('/dedicatedCloud/'+str(t))
		if r1['state']=='delivered':
			datacenter_list=client.get('/dedicatedCloud/'+str(t)+'/datacenter')
			for dc in datacenter_list:
				HPC_instance_list=client.get('/dedicatedCloud/'+str(t)+'/datacenter/'+str(dc)+'/vm')
				for instance in HPC_instance_list:
					# logging.info('/dedicatedCloud/'+str(t)+'/datacenter/'+str(dc)+'/vm/'+str(instance))
					for i in range(5):
						try:
							inst_details =client.get('/dedicatedCloud/'+str(t)+'/datacenter/'+str(dc)+'/vm/'+str(instance))
							name=inst_details['name']
							CPU=inst_details['cpuUsed']
							CPUM=inst_details['cpuMax']
							RAM=inst_details['memoryUsed']
							RAMM=inst_details['memoryMax']
							if CPU>CPUM:logging.info(["CPU>CPUM",'/dedicatedCloud/'+str(t)+'/datacenter/'+str(dc)+'/vm/'+str(instance),inst_details])	

							try:dedicatedCloud[t,dc,name,tt2,"cpu_moy"]+=CPU
							except:dedicatedCloud[t,dc,name,tt2,"cpu_moy"]=CPU
							try:dedicatedCloud[t,dc,name,tt2,"cpu_pic"]=max(dedicatedCloud[t,dc,name,tt2,"cpu_pic"],CPU)
							except:dedicatedCloud[t,dc,name,tt2,"cpu_pic"]=CPU
							dedicatedCloud[t,dc,name,tt2,"cpu_max"]=CPUM

							try:dedicatedCloud[t,dc,name,tt2,"ram_moy"]+=RAM
							except:dedicatedCloud[t,dc,name,tt2,"ram_moy"]=RAM
							try:dedicatedCloud[t,dc,name,tt2,"ram_pic"]=max(dedicatedCloud[t,dc,name,tt2,"ram_pic"],RAM)
							except:dedicatedCloud[t,dc,name,tt2,"ram_pic"]=RAM
							dedicatedCloud[t,dc,name,tt2,"ram_max"]=RAMM

							try:dedicatedCloud[t,dc,name,tt2,"n"]+=1
							except:dedicatedCloud[t,dc,name,tt2,"n"]=1

							logging.info(["ram cpu usage",t,dc,name,RAM,RAMM,CPU,CPUM,tt2])
							break
						except:
							continue
	with open('dedicatedCloud_saved_dictionary.pkl','wb') as f:
		pickle.dump(dedicatedCloud,f)
	return dedicatedCloud

def aggregate_dedicatedCloud_cpu_ram(dedicatedCloud):
	instance_list=[]
	for t,dc,name,tt2,typee in dedicatedCloud:
		if typee=="n":
			n=dedicatedCloud[t,dc,name,tt2,"n"]
			ram_moy=dedicatedCloud[t,dc,name,tt2,"ram_moy"]/n
			ram_pic=dedicatedCloud[t,dc,name,tt2,"ram_pic"]
			ram_max=dedicatedCloud[t,dc,name,tt2,"ram_max"]
			cpu_moy=dedicatedCloud[t,dc,name,tt2,"cpu_moy"]/n
			cpu_pic=dedicatedCloud[t,dc,name,tt2,"cpu_pic"]
			cpu_max=dedicatedCloud[t,dc,name,tt2,"cpu_max"]
			instance_list.append([t,dc,name,ram_moy,ram_pic,ram_max,cpu_moy,cpu_pic,cpu_max,tt2])
	return instance_list

def all_extraction():
	# pour eviter qu'un tenant soit traité via un autre compte racine
	# on choisi un seul client pour chaque tenant
	tenant_dict={}
	tenant_dict_HPC={}
	tenant_dict_VPS={}
	tenant_id_dict={}
	nich_set=set()
	#Connexion à l'API OVH pour chaque compte client
	for file in os.listdir('Conf_token'):
		c=ovh.Client(config_file=config['API_Token']['Folder_path']+str(file))
		# Récupération de la liste des tenants du compte
		tenant_list=sorted(list(set(c.get('/cloud/project'))))
		for t in tenant_list:tenant_dict[t]=c
		tenant_list=sorted(list(set(c.get('/dedicatedCloud'))))
		for t in tenant_list:tenant_dict_HPC[t]=c
		tenant_list=sorted(list(set(c.get('/vps'))))
		for t in tenant_list:tenant_dict_VPS[t]=c
		#Récupération de la liste des services déployés sur
		tenant_id_list=c.get('/services') 
		for t in tenant_id_list:tenant_id_dict[t]=c

		nich=c.get('/me')['nichandle']
		nich_set.add(nich)

	tenant_instance_list0=fetch_public_cloud_instance_current(tenant_dict)
	csv_write(csv_output0,header0,tenant_instance_list0)

	global_history1=fetch_history_instance(tenant_dict)
	csv_write(csv_output1,header1,global_history1)

	global_history2=fetch_history_service(tenant_dict)
	csv_write(csv_output2,header2,global_history2)

	global_history3=fetch_history_snapshot(tenant_dict)
	csv_write(csv_output3,header3,global_history3)

	global_history4=fetch_history_storage(tenant_dict)
	csv_write(csv_output4,header4,global_history4)

	instance_lista=fetch_public_cloud_instance_info(tenant_dict)
	instance_listb=fetch_HPC_cloud_instance_info(tenant_dict_HPC)
	instance_listc=fetch_VPS_instance_info(tenant_dict_VPS)
	instance_list5=instance_lista+instance_listb+instance_listc
	csv_write(csv_output5,header5,instance_list5)

	tenant_list,GW_LB_list_global=fetch_tenant_info(tenant_id_dict)
	csv_write(csv_output6,header6,tenant_list)
	csv_write(csv_output7,header7,GW_LB_list_global)
	missing_list=detect_missing_token(nich_set,tenant_list)
	csv_write(csv_output8,header8,missing_list)

	Calcul_inducteurs.compute()
	Info_users.compute()

def extract_private_cloud_resources_usage():
	# pour eviter qu'un tenant soit traité via un autre compte racine
	# on choisi un seul client pour chaque tenant
	tenant_dict_HPC={}
	#Connexion à l'API OVH pour chaque compte client
	for file in os.listdir('Conf_token'):
		c=ovh.Client(config_file=config['API_Token']['Folder_path']+str(file))

		# Obtenir les informations sur le token
		# token_info = c.get('/auth/currentCredential')
		# # Afficher la date d'expiration
		# logging.info(["La date d'expiration du token est :",file,token_info])
		# # logging.info(["La date d'expiration du token est :",file,token_info['expiration']])

		try:
			tenant_list=sorted(list(set(c.get('/dedicatedCloud'))))
			for t in tenant_list:tenant_dict_HPC[t]=c
		except:
			logging.info(["problem token",file])
			s=traceback.format_exc()
			logging.info(["raise",s])

	dedicatedCloud=fetch_dedicatedCloud_cpu_ram(tenant_dict_HPC)
	global_history9=aggregate_dedicatedCloud_cpu_ram(dedicatedCloud)
	csv_write(csv_output9,header9,global_history9)

def read_sharepoint():
	context_auth = AuthenticationContext(url=sharepoint_site_url)
	context_auth.acquire_token_for_app(client_id=sharepoint_client_id,client_secret=sharepoint_client_secret)
	ctx = ClientContext(sharepoint_site_url, context_auth)

	# get the files in the folder        
	libraryRoot = ctx.web.get_folder_by_server_relative_path(sharepoint_relative_url+"/Conf_token")
	files = libraryRoot.files
	ctx.load(files)
	ctx.execute_query()
	for f in files:
		logging.info(["Download token",f])
		f=str(f)
		response = File.open_binary(ctx,sharepoint_relative_url+"/Conf_token/"+f)
		with open("./Conf_token/"+f, "wb") as local_file:
			local_file.write(response.content)

	response = File.open_binary(ctx,sharepoint_relative_url+"/CMDB/CMDB.xlsx")
	with open("./CMDB.xlsx", "wb") as local_file:
		local_file.write(response.content)

def read_cmdb(path_to_xls):
	logging.info(["lecture de la CMDB",path_to_xls])
	xls = pd.ExcelFile(path_to_xls)
	df1 = pd.read_excel(xls, '3. Appli-Tenant')
	df2 = pd.read_excel(xls, '6. Mapping VM')
	df1['ratio'] = df1['TVA'] * df1['Réduction Marché'] * df1['Coût support OVH']	
	Tenant_to_ratio = dict(zip(df1['Tenant ID'],df1['ratio']))
	logging.info(["Tenant_to_ratio",Tenant_to_ratio])
	df2.to_csv("instances_rules.csv",sep=',',encoding='utf-8',index=False)
	return Tenant_to_ratio

def send_sharepoint(tt1):
	context_auth = AuthenticationContext(url=sharepoint_site_url)
	context_auth.acquire_token_for_app(client_id=sharepoint_client_id,client_secret=sharepoint_client_secret)

	ctx = ClientContext(sharepoint_site_url, context_auth)

	# creat folder tt1
	libraryRoot = ctx.web.get_folder_by_server_relative_path(sharepoint_relative_url+"/Archive")
	ctx.load(libraryRoot)
	ctx.execute_query()
	libraryRoot.add(tt1)
	ctx.execute_query()
	# logging.info(dir(libraryRoot))

	# upload a file into an archive folder
	libraryRoot = ctx.web.get_folder_by_server_relative_path(sharepoint_relative_url+"/Archive/"+tt1)
	ctx.load(libraryRoot)
	ctx.execute_query()
	# logging.info(libraryRoot)
	for localpath in glob.glob(csv_output+"/*.csv"): 
		logging.info(["Upload csv to archive folder",localpath])
		remotepath=os.path.basename(localpath)
		with open(localpath,'rb') as content_file:
			file_content = content_file.read()
			libraryRoot.upload_file(remotepath,file_content).execute_query()

	# upload the principal folder
	libraryRoot = ctx.web.get_folder_by_server_relative_path(sharepoint_relative_url+"/CSV_output")
	ctx.load(libraryRoot)
	ctx.execute_query()
	# logging.info(libraryRoot)
	for localpath in glob.glob(csv_output+"/*.csv"): 
		logging.info(["Upload csv to principal folder",localpath])
		remotepath=os.path.basename(localpath)
		with open(localpath,'rb') as content_file:
			file_content = content_file.read()
			libraryRoot.upload_file(remotepath,file_content).execute_query()

def date_time_refresh(tt):
	csv_write(csv_output10,header10,[[tt]])

def get_next_hour():
	tt1=ts_to_local_time_str(time.time())
	mm=int(tt1[14:16])
	if mm>=15:
		tt15=ts_to_local_time_str(local_time_str_to_ts(tt1[:14]+"15"+tt1[16:-2]+"00")+3600)
	else:
		tt15=ts_to_local_time_str(local_time_str_to_ts(tt1[:14]+"15"+tt1[16:-2]+"00"))
	return(tt15)

def send_email(tt,s):
	# Voici l’email destinataire des mails d’alerte : Exemple@exemple.com
	subject="rapport d'extraction "+str(tt)
	text="python email: "+str(tt)+'\n'
	for t in unknown_tenant_ratio:
		text+="Le tenant "+str(t)+" n'est pas associé à des ratios dans la CMDB"+'\n'
	text+=s
	message = 'Subject: {}\n\n{}'.format(subject,text)
	mailserver = smtplib.SMTP('SMTP_server_ip',SMTP_server_port)
	mailserver.ehlo()
	mailserver.starttls()
	mailserver.login('email_client_id', 'email_client_secret')
	#Adding a newline before the body text fixes the missing message body
	mailserver.sendmail('email_client_id','adress',message.encode('cpxxx'))
	mailserver.quit()

# try:
# 	with open('dedicatedCloud_saved_dictionary.pkl','rb') as f:
# 		dedicatedCloud=pickle.load(f)
# except:None

# for k in dedicatedCloud:
# 	print(k,dedicatedCloud[k])
# sys.exit(1)

# # YYYY-MM-DD-HH-mm-ss
# next_tt="2024-03-26-16-15-00"
# HH=int(next_tt[11:13])
# MM=int(next_tt[5:7])
# next_month_j_0=ts_to_local_time_str(local_time_str_to_ts(next_tt)+3600)[5:7]
# next_month_j_1=ts_to_local_time_str(local_time_str_to_ts(next_tt)+3600+3600*24)[5:7]
# print(next_tt,HH,MM!=next_month_j_0,MM!=next_month_j_1)
# sys.exit(1)

def closelog(handlers):
	for handler in handlers:
		handler.close()

begin=True
while True:
	ts=str(int((time.time()*100)))
	next_tt=get_next_hour()
	reload(logging)
	handlers = [logging.FileHandler("log/"+next_tt+'_'+ts+'.log'), logging.StreamHandler()]
	logging.basicConfig(level=logging.INFO ,format='%(message)s',handlers=handlers)
	# logging.basicConfig(level=logging.DEBUG,format='%(message)s',handlers=handlers)
	logging.info(["next tt",next_tt])
	try:
		HH=int(next_tt[11:13])
		MM=int(next_tt[5:7])
		next_month_j_0=ts_to_local_time_str(local_time_str_to_ts(next_tt)+3600)[5:7]
		next_month_j_1=ts_to_local_time_str(local_time_str_to_ts(next_tt)+3600+3600*24)[5:7]
		if not begin:
			pause.until(local_time_str_to_ts(next_tt))
		date_time_refresh(next_tt)
		read_sharepoint()
		Tenant_to_ratio=read_cmdb("./CMDB.xlsx")
		extract_private_cloud_resources_usage()
		# if HH==23 or begin:
		# 	all_extraction()
		# 	logging.info(list(unknown_tenant_ratio))
		# 	send_sharepoint(next_tt)
		# 	send_email(next_tt,"extraction avec succès\n")
		begin=False
		closelog(handlers)
	except:
		s=traceback.format_exc()
		logging.info(["raise",s])
		send_email(next_tt,s)
		closelog(handlers)
		pause.minutes(15)
