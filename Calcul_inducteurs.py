# -*- encoding: utf-8 -*-
import configparser
import csv
import re
import time
tt="_"+str(int(time.time()))
tt=""

#Lecture du fichier de configuration
conf=configparser.ConfigParser()
conf.sections()
conf.read('scripts_conf.ini')
conversion={'GW':'Gateway','LB':'Loadbalancer'}

# Chemin du fichier csv inducteurs de sortie (exploité par Power BI)
csv_ind_SAS_Sante=conf['csv_output']['Calcul_inducteurs_SAS_Sante']
csv_ind_ProSanteConnect=conf['csv_output']['Calcul_inducteurs_ProSanteConnect']
csv_ind_SIVIC_SICAP=conf['csv_output']['Calcul_inducteurs_SIVIC_SICAP']

# Chemin du fichier contenant les infos à lire
csv_instances=conf['csv_output']['Info_instances']
csv_services=conf['csv_output']['Info_services']
csv_instances_rules='instances_rules.csv'

def csv_read(csv_file,logging):
	return[r for r in csv.DictReader(open(csv_file,'r'))]

def regex1(s):
	return'^'+s.replace('d','\d').replace('*','.*')+'$'

#Fonction d'écriture des données dans un fichier csv
def csv_write(csv_file,ct):
	data_writer=csv.writer(open(csv_file[:-4]+tt+'.csv','w',encoding="cp1252",errors='replace'),delimiter=',')
	data_writer.writerow([k for k in ct])
	data_writer.writerow([ct[k]for k in ct])

# Fonction de comptage des inducteurs d'infogérance sur les VM et les services
# de l'application SAS/Santé.fr
def count_SAS_Sante(instance_list,instance_rules_list,service_list,logging):
	ct={}
	#Comptage selon la convention de nommage des VM
	for i in instance_list:
		for r in instance_rules_list:
			if re.search(regex1(r['Tenant ID']),i['Tenant ID']):
				if re.search(regex1(r['Instance Name']),i['Instance Name']):
					if re.search(regex1(r['Region']),i['Region']):
						k=r['output']
						if k in ct:ct[k]+=1
						else:ct[k]=1
						logging.info([i['Tenant ID'],';',i['Instance Name'],';',i['Region'],';',k])
						break
	for service in service_list:
		if re.search(regex1('..-01-55-*ddd'),service['Service name']):
			k=service['Service name'][:2]
			if k in conversion:k=conversion[k]
			else:k='Other'
			if k in ct:ct[k]+=1
			else:ct[k]=1
	logging.info([ct])
	#Ecriture des données de SAS/Santé.fr
	csv_write(csv_ind_SAS_Sante,ct)
	return ct

# Fonction de comptage des inducteurs d'infogérance sur les VM de 
# l'application ProSanteConnect
def count_inst_ProSanteConnect(instance_list,logging):
	ct={'Prod':0}
	for i in instance_list:
		if re.search('(^vps-\w+\.vps\.ovh\.net$)|(^vps\w+\.ovh\.net$)'\
			,i['Instance ID']):
			ct['Prod']+=1
	logging.info([ct])
	#Ecriture des données de ProsantéConnect
	csv_write(csv_ind_ProSanteConnect,ct)
	return ct

# Fonction de comptage des inducteurs d'infogérance sur les VM de 
# l'application SIVIC/SICAP
def count_inst_SIVIC_SICAP(instance_list,logging):
	ct={'Prod':0}
	for i in instance_list:
		if re.search('^vps-\w+\.vps\.ovh\.net$',i['Instance ID']):
			ct['Prod']+=1
	logging.info([ct])
	#Ecriture des données de SIVIC/SICAP
	csv_write(csv_ind_SIVIC_SICAP,ct)
	return ct

def compute(logging):
	# Lecture du fichier csv contenant les info sur les instances déployées
	instance_list=csv_read(csv_instances,logging)
	# Lecture du fichier csv contenant les info sur les services déployés
	instance_rules_list=csv_read(csv_instances_rules,logging)
	service_list=csv_read(csv_services,logging)
	count_SAS_Sante(instance_list,instance_rules_list,service_list,logging)
	count_inst_ProSanteConnect(instance_list,logging)
	count_inst_SIVIC_SICAP(instance_list,logging)
