# Prod-Script-Finops
## Contexte
Dans le cadre de son initiative d'adoption du cloud, l'Agence du Numérique en Santé (ANS) a récemment migré trois systèmes d'information (SI) vers l'hébergement cloud d'OVH, utilisant les offres suivantes : OVH Public Cloud et OVH Hosted Private Cloud qualifiée SecNumCloud. En parallèle, l'ANS a développé une application de reporting FinOps, composée de scripts Python et de rapports Power BI, permettant de suivre hebdomadairement la consommation des ressources cloud et d’auditer les comptes administrateurs.
## Fonctionnalités
L’outil développé permet d’extraire des API OVH et de calculer les fichiers d’indicateurs suivants, générés au format CSV. 
1. Les indicateurs de facturation incluent :

a) data_PBI_info_billing

b) data_PBI_info_billing_history

c) data_PBI_info_billing_snapshot

d) data_PBI_info_billing_storage

e) data_PBI_info_billing_managed_public_cloud

2.	Les indicateurs d’information technique des instances, des tenants et des services :

a) data_PBI_info_instance

b) data_PBI_info_tenant

c) data_PBI_info_service

3.	data_PBI_info_usage : cet indicateur fournit les taux quotidiens de consommation du CPU et de la mémoire RAM pour chaque machine virtuelle du cloud privé.
  
4.	Les indicateurs des trois SI actuels :

a) Calcul_inducteurs_ProSanteConnect

b) Calcul_inducteurs_SAS_Sante

c) Calcul_inducteurs_SIVIC_SICAP

5.	data_PBI_info_users : Information des différents utilisateurs des applications.

Ces fichiers CSV sont extraits :

•	chaque dimanche à 23h15.

•	à la fin de chaque mois à 23h15.

•	la veille de la fin de chaque mois à 23h15.

Une fois les fichiers extraits, ils sont déposés sur un dossier SharePoint pour être traités par des rapports Power BI.
## Les fichiers Python
Dans le dossier principal, on trouve les fichiers suivants :

1.	compute_all.py : le script principal où se trouve les fonctions des SI;

2.	Calcul_inducteurs.py : le script de calcul des inducteurs des différents SI ;
   
3.	Info_users.py : le script d’extraction des informations des utilisateurs ;
   
4.	scripts_conf.ini : les fichiers de paramétrage local comportant les différents noms de fichiers CSV et les chemins d’accès locaux pour le stockage des résultats ;
   
5.	dedicatedCloud_saved_dictionary.pkl : le fichier sérialisé contenant l’archive des différentes mesures horaires de la consommation de RAM et de CPU pour le calcul du fichier data_PBI_info_usage mentionné dans la section « Fonctionnalités ».
    
Les éléments suivants seront à créer et adapter en fonction du projet : 

-	CMDB.xlsx : le fichier Excel qui comporte des feuilles nécessaires pour le mapping des machines virtuelles (VM) et les ratios de facturation associés à chaque tenant. Les feuilles sont les suivantes : Liste utilisateurs, Appli-Tenant, Mapping VM, Applications, Domaine-Entreprise, Localisation.

-	Conf_token : le sous dossier qui contient les fichiers textes avec les différents tokens de l’API OVH associés à chaque application (SI) ;

-	Parameters.py : un fichier de configuration pour l'authentification au SharePoint qui contient les secrets.
  
