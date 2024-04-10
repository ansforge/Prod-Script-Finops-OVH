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
csv_ind_projet1=conf['csv_output']['Calcul_inducteurs_projet1']
csv_ind_projet2=conf['csv_output']['Calcul_inducteurs_projet2']
csv_ind_projet3=conf['csv_output']['Calcul_inducteurs_projet3']

# Chemin du fichier contenant les infos à lire
csv_instances=conf['csv_output']['Info_instances']
csv_services=conf['csv_output']['Info_services']
csv_instances_rules='instances_rules.csv'

def csv_read(csv_file):
	return[r for r in csv.DictReader(open(csv_file,'r'))]

def regex1(s):
	return'^'+s.replace('d','\d').replace('*','.*')+'$'

#Fonction d'écriture des données dans un fichier csv
def csv_write(csv_file,ct):
	data_writer=csv.writer(open(csv_file[:-4]+tt+'.csv','w',encoding="cp1252",errors='replace'),delimiter=',')
	data_writer.writerow([k for k in ct])
	data_writer.writerow([ct[k]for k in ct])

# Fonction de comptage des inducteurs d'infogérance sur les VM et les services
# de l'application projet1
def count_projet1(instance_list,instance_rules_list,service_list):
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
						print(i['Tenant ID'],';',i['Instance Name'],';',i['Region'],';',k)
						break
	for service in service_list:
		if re.search(regex1('..-01-55-*ddd'),service['Service name']):
			k=service['Service name'][:2]
			if k in conversion:k=conversion[k]
			else:k='Other'
			if k in ct:ct[k]+=1
			else:ct[k]=1
	print(ct)
	#Ecriture des données de projet1
	csv_write(csv_ind_projet1,ct)
	return ct

# Fonction de comptage des inducteurs d'infogérance sur les VM de 
# l'application projet2
def count_inst_projet2(instance_list):
	ct={'Prod':0}
	for i in instance_list:
		if re.search('(^vps-\w+\.vps\.ovh\.net$)|(^vps\w+\.ovh\.net$)'\
			,i['Instance ID']):
			ct['Prod']+=1
	print(ct)
	#Ecriture des données de projet2
	csv_write(csv_ind_projet2,ct)
	return ct

# Fonction de comptage des inducteurs d'infogérance sur les VM de 
# l'application projet3
def count_inst_projet3(instance_list):
	ct={'Prod':0}
	for i in instance_list:
		if re.search('^vps-\w+\.vps\.ovh\.net$',i['Instance ID']):
			ct['Prod']+=1
	print(ct)
	#Ecriture des données de projet3
	csv_write(csv_ind_projet3,ct)
	return ct

def compute():
	# Lecture du fichier csv contenant les info sur les instances déployées
	instance_list=csv_read(csv_instances)
	# Lecture du fichier csv contenant les info sur les services déployés
	instance_rules_list=csv_read(csv_instances_rules)
	service_list=csv_read(csv_services)
	count_projet1(instance_list,instance_rules_list,service_list)
	count_inst_projet2(instance_list)
	count_inst_projet3(instance_list)