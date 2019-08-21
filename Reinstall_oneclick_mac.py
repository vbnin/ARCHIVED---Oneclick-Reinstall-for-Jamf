#!/usr/local/bin/python2.7
# -*- coding: utf-8 -*-

"""
Programmers : VBNIN - IPEchanges
Python version : 2.7.16
This python app allows the user to reset its session with default settings loaded from the JAMF server

Changelog :

v0.1.1 : App creation
v0.2.2 : App working for computer reset
v0.3.1 : App modified to check for local installers and remote installers on Jamf
v0.3.2 : Modified the error messages during execution
v0.3.3 : Modifications added to make the script OK
v0.4.1 : Code modified to check if local installer exists before remote download
v0.4.2 : Removed support phone number
v0.4.3 : Added support for forbidden character in computer's name
v0.4.4 : Changed color for ongoing download
v0.4.5 : add list_building fonction for only admin
v0.5.2 : Added mdm profile removing
v0.6.1 : Disabled MDM profile removing and added json export to distant SFTP
v0.6.2 : Modified reinstall command in delete computer function (removed applicationpath flag)
v0.7.1 : Massive code update
v0.7.2 : Changed the location of log button
v0.7.3 : Removed pop up after launch reset command
v0.7.4 : Added autologon option
v0.7.5 : Added caffeine module to prevent mac from sleeping
v0.7.6 : Added jamfHelper splash screen before reboot
"""

title = 'JAMF OneClick Reinstall'
version = 'Version 0.7.6 - 21/08/2019'


###########################################################################
#### Import internal libraries
###########################################################################
import Tkinter as tk
import tkMessageBox
import ttk
import tkFont as tkfont 
import logging
import sys
import os
import subprocess
import re
import threading
import time
import csv
import json
from logging.handlers import RotatingFileHandler


###########################################################################
### Activatin main logger in a rotated log file
###########################################################################
try:
    logs_file = '/var/log/jamf_ftv.log'
    handler = RotatingFileHandler(logs_file, maxBytes=10000000, backupCount=5)
    handler.setFormatter(logging.Formatter('%(asctime)s : %(message)s'))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s : %(message)s')
    log = logging.getLogger(__name__)
    log.addHandler(handler)
    log.info("Initialisation du fichier de log dans {}".format(logs_file))
except Exception as e:
    sys.exit("*** Erreur *** Impossible d'initialiser le fichier de logs : {}".format(e))


###########################################################################
### Tools API Jamf
###########################################################################
def get_serial():
    """Getting computer's serial number"""
    try:
        cmd = "system_profiler SPHardwareDataType | grep 'Serial Number' | awk '{print $4}'"
        result = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        sn = [line for line in result.stdout]
        my_serial = re.sub(r'\W+', '', sn[0])
        log.info('Votre numéro de série est : {}'.format(my_serial))
        return my_serial
    except:
        return None

def list_computers(headers, auth):
    '''List all the computers in Jamf'''
    url = jamf['url_jamf'] + '/JSSResource/computers'
    response = requests.get(url, headers=headers, auth=(auth['api_user'], auth['api_pass']))
    return response.json()['computers']

def list_buildings(headers, auth):
    '''List all the available buildings in Jamf'''
    url = jamf['url_jamf'] + '/JSSResource/buildings'
    response = requests.get(url, headers=headers, auth=(auth['api_user'], auth['api_pass']))
    buildings = []
    for building in response.json()['buildings']:
        buildings.append(building["name"])
    return buildings
  
def computer_detail(id, headers, auth):
    '''Get all the details of this Mac.'''
    url = jamf['url_jamf'] + '/JSSResource/computers/id/{}'.format(id)
    response = requests.get(url, headers=headers, auth=(auth['api_user'], auth['api_pass']))
    return response.json()['computer']

def search_local_installer(recommended_version):
    '''Search for a macOS installer and check its version in the package'''
    try:
        version_last_digits = recommended_version[3:]
        file = "/Applications/install macOS Mojave.app/Contents/version.plist"
        with open(file, "r") as f:
            content = f.read()
        if version_last_digits in content:
            log.info("Installeur local compatible détecté")
            return "install macOS Mojave"
        else:
            log.info("Installeur local détecté mais version non compatible avec les recommandations Jamf : {}".format(recommended_version))
            return False
    except IOError:
        log.warning("Aucun installeur macOS local trouvé dans /Applications")
        return False
    except Exception as e:
        log.error("Erreur inconnue dans search_local_installers : {}".format(e))
        return False

def list_policies(headers, auth, match):
    '''List all the available policies in Jamf and keep only the relevant ones'''
    try:
        url = jamf['url_jamf'] + '/JSSResource/policies'
        response = requests.get(url, headers=headers, auth=(auth['api_user'], auth['api_pass']))
        policies = []
        log.info('Sélection des policies Jamf dont le nom contient : "{}"'.format(match))
        for policy in response.json()['policies']:
            if match in policy["name"]:
                policies.append(policy["name"])
        return policies
    except Exception as e:
        log.error("Erreur inconnue dans lisst_policies : {}".format(e))

def get_policy_details(headers, auth, policy):
    '''Get the event trigger for a designated policy'''
    policy = policy.split(' ')
    policy = "%20".join(policy)
    url = jamf['url_jamf'] + '/JSSResource/policies/name/{}'.format(policy)
    response = requests.get(url, headers=headers, auth=(auth['api_user'], auth['api_pass']))
    return response.json()

def get_computer_history(headers, auth, id):
    '''Get a full jamf history of this Mac.'''
    try:
        url = jamf['url_jamf'] + '/JSSResource/computerhistory/id/{}'.format(id)
        response = requests.get(url, headers=headers, auth=(auth['api_user'], auth['api_pass']))
        return response.json()
    except Exception as e:
        log.error("Erreur pendant la récupération de l'historique Jamf ! Raison : {}".format(e))
        return None

def json_to_csv(json_file, serial, name):
    '''Export a JSON object to a file'''
    try:
        now = time.strftime('%y%m%d-%H%M%S')
        title = "{}_history_{}_{}.json".format(now, serial, name)
        file_path = '/tmp/{}'.format(title)
        with open(file_path, 'w') as json_output:
            json.dump(json_file, json_output)
        return file_path
    except Exception as e:
        log.error('Erreur pendant la création du fichier JSON local ! Raison : {}'.format(e), exc_info=True)
        return None

def sftp_upload(file_to_upload):
    try:
        address_and_port = jamf['sftp_address'].split(':')
        address = address_and_port[0]
        port = address_and_port[1]

        user_and_pswd = jamf['sftp_credentials'].split(':')
        user = user_and_pswd[0]
        pswd = user_and_pswd[1]

        cnopts = pysftp.CnOpts()
        cnopts.hostkeys = None
        cnopts.log = True
        srv = pysftp.Connection(
            host=address,
            username=user,
            password=pswd,
            port=int(port),
            cnopts=cnopts
        )
        log.info('Connection réussie avec {}'.format(jamf['sftp_address']))
    except Exception as e:
        log.error("Erreur pendant la connexion avec {} - raison : {}".format(jamf['sftp_address'], e))
        return False

    try:
        with srv.cd(sftp_root):
            srv.put(file_to_upload)
    except Exception as e:
        log.error("Erreur pendant l'upload du fichier {} - raison : {}".format(file_to_upload, e), exc_info=True)
    else:
        return True

def upload_history(headers, auth, comp_id, serial, name):
    '''Function to upload a history toward a SFTP server'''
    log.info("Récupération de l'historique depuis la base de données Jamf")
    history = get_computer_history(headers, auth, comp_id)
    if history is not None:
        log.info("Conversion de l'historique JSON en fichier JSON local")
        file_to_upload = json_to_csv(history, serial, name)
        if file_to_upload is not None:
            log.info("Fichier {} créé, démarrage de l'upload SFTP...".format(file_to_upload))
            if sftp_upload(file_to_upload) is True:
                log.info("Historique Jamf uploadé avec succès vers {}".format(jamf['sftp_address']))
                return True
            else:
                return False
        else:
            return False
    else:
        return False

def delete_computer(computer_id, auth):
    '''Delete the given computer from Jamf'''
    url = jamf['url_jamf'] + '/JSSResource/computers/id/{}'.format(computer_id)
    response = requests.delete(url, auth=(auth['api_user'], auth['api_pass']))
    response = "{}".format(response)
    if response == '<Response [200]>':
        return True
    else:
        log.error("Echec de la suppression de la DB Jamf ! Réponse du serveur : {}".format(response))
        return False

def launch_reset(app):
    '''Launch the reset command'''
    app_backslash = app.split(' ')
    app_backslash = r'\ '.join(app_backslash)
    cmd = r'/Applications/{}.app/Contents/Resources/startosinstall --eraseinstall --newvolumename "Macintosh HD" --nointeraction --agreetolicense >> {}'.format(app_backslash, logs_file)
    log.info('Running command : {}'.format(cmd))
    subprocess.call(cmd, shell=True)
    return True

def jamf_cmd(cmd):
    '''Launch a custom Jamf command'''
    try:
        cmd = cmd.split(' ')
        cmd_line = ['/usr/local/bin/jamf'] + cmd 
        inventory = subprocess.Popen(cmd_line, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (out, err) = inventory.communicate()
        if inventory.returncode == 0:
            log.info("Commande JAMF '{}' exécutée. Résultat : {}".format(cmd, out))
            return True
        else:
            raise Exception(err)
    except Exception as e:
        log.error("Erreur : pendant l'exécution de la commande JAMF '{}' : {}".format(cmd, e))
        return False

def show_logs(event=None):
    '''Launch a shell command to open log Console on the specified logfile'''
    subprocess.call("open -a Console {}".format(logs_file), shell=True)
    
def show_jamfhelper():
    # Splash Screen Jamf Helper variables
    jamfHelper = "/Library/Application Support/JAMF/bin/jamfHelper.app/Contents/MacOS/jamfHelper"
    heading = "Redémarrage en cours"
    description = "Veuillez patienter, votre Mac va redémarrer dans quelques instants..."
    icon = "/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/NetBootVolume.icns"

    # Launch Splash Screen
    subprocess.Popen('"{}" -windowType fs -heading "{}" -description "{}" -icon "{}" &'.format(jamfHelper, heading, description, icon), shell=True)


###########################################################################
### This is the main class
###########################################################################
class JamfOneClickReinstall():
    ''' This class runs the main window of the application '''
    def __init__(self, root):
        # Jamf API headers
        self.json_headers = {
            'Accept':'application/json'
        }

        # Checkin computer serial number
        self.my_serial = get_serial()
        if self.my_serial is None:
            log.error("Erreur : impossible de déterminer le numéro de série de ce Mac !")
            sys.exit(1)

        # Initializing root window
        root.title_font = tkfont.Font(family='Helvetica', size=18, weight="bold")
        root.title(title + ', ' + version)
        root.resizable(False, False)
        root.tk_setPalette(background='#ececec')
        width = 900
        height = 400
        x = int(root.winfo_screenwidth() / 2 - width / 2)
        y = int(root.winfo_screenheight() / 2 - height / 2)
        root.geometry("{}x{}+{}+{}".format(width, height, x, y))
        root.bind("<Return>", self.connect)

        # Creating the container frame
        self.container = tk.Frame(master=root)
        self.container.pack(side="top", fill="both", expand=True)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        # Launching first frame
        self.frame()

        # Displaying credentials frame or using autologon
        if jamf['autologon'].lower() == 'oui':
            self.connect(autologon='oui')
        else:
            self.user_login_frame()

#############################################
### Class tools
#############################################
    def info(self, title, msg):
        '''Display an info popup and logs to file'''
        log.info(msg)
        tkMessageBox.showinfo(title, msg)
        root.update()
        
    def error(self, title, msg):
        '''Display an error popup and logs to file'''
        log.error(msg)
        tkMessageBox.showinfo(title, msg)
        root.update()

    def connect(self, event=None):
        '''Try to connect to Jamf api server by listing all buildings in jamf. If succeed : connect is OK'''
        try:
            self.auth = {
                'api_user':self.log_user.get(),
                'api_pass':self.log_pswd.get()
            }
            list_buildings(self.json_headers, self.auth)
        except ValueError:
            self.error("Erreur de connexion", "Identifiants invalides ou non autorisés...")
        except requests.ConnectionError:
            self.error("Erreur de connexion", "Serveur Jamf injoignable, veuillez vérifier votre accès réseau...")
        except Exception as e:
            self.error("Erreur de connexion", "Impossible de lancer la connexion au serveur Jamf.\nRaison : {}".format(e))
        else:
            log.info("Identifiant API Jamf '{}' connecté".format(self.auth['api_user']))
            self.login_frame.destroy()
            self.wait = tk.Label(self.main_frame, text='Veuillez patienter...', font='System 50 bold')
            self.wait.pack(fill='both', anchor='center', pady=50)
            root.update()
            root.after(500, self.get_jamf_info)

    def connect(self, autologon=None, event=None):
        '''Try to connect to Jamf api server by listing all buildings in jamf. If succeed : connect is OK'''
        try:
            if autologon == 'oui':
                self.auth = {
                        'api_user':jamf['api_user'],
                        'api_pass':jamf['api_pswd']
                    }
            else:
                self.auth = {
                    'api_user':self.log_user.get(),
                    'api_pass':self.log_pswd.get()
                }
            list_buildings(self.json_headers, self.auth)
        except ValueError:
            self.error("Erreur de connexion", "Identifiants invalides ou non autorisés...")
            root.update()
        except requests.ConnectionError:
            self.error("Erreur de connexion", "Serveur Jamf injoignable, veuillez vérifier votre accès réseau...")
            root.update()
        except Exception as e:
            self.error("Erreur de connexion", "Impossible de lancer la connexion au serveur Jamf.\nRaison : {}".format(e))
            root.update()
        else:
            log.info("Identifiant API Jamf '{}' connecté".format(self.auth['api_user']))
            try:
                self.login_frame.destroy()
            except:
                pass
            self.wait = tk.Label(self.main_frame, text='Veuillez patienter...', font='System 50 bold')
            root.update()
            self.wait.pack(fill='both', anchor='center', pady=100)
            root.after(500, self.get_jamf_info)
            
    def get_jamf_info(self):
        '''Search for this computer in Jamf'''
        try:
            match = False
            for computer in list_computers(self.json_headers, self.auth):
                comp = computer_detail(computer['id'], self.json_headers, self.auth)
                if comp['general']['serial_number'] == self.my_serial:
                    log.info("Ce Mac a été identifié dans jamf, {} avec l'ID {}".format(comp['general']['name'].encode("utf-8"), comp['general']['id']))
                    self.my_mac = comp
                    self.my_id = comp['general']['id']
                    self.my_name = comp['general']['name']
                    match = True
                    break
            if match is True:
                self.wait.destroy()
                self.show_config_frame()
            else:
                self.error('Erreur Jamf', "Aucun lien entre le numéro de série de ce Mac et la base de données Jamf !\nL'application va quitter...")
                sys.exit(1)
        except Exception as e:
            root.update()
            text = "Une erreur a empêché la récupération des informations Jamf.\nVeuillez tenter de rafraichir les champs manuellement ou contacter le support IP Echanges\n\nRaison : {}".format(e)
            confirm = tkMessageBox.askokcancel("Erreur Jamf", text)
            if confirm is True:
                root.after(1000, self.get_jamf_info)
    
    def resync(self):
        '''Update the fields with a Jamf poll'''
        for frame in [self.reset_title_frame, self.reset_frame, self.reset_button_frame]:
            try:
                frame.destroy()
            except:
                pass
        self.wait = tk.Label(self.main_frame, text='Veuillez patienter...', font='System 50 bold')
        self.wait.pack(fill='both', anchor='center', pady=50)
        root.after(500, self.get_jamf_info)
    
#############################################
### Frames 
#############################################
    def frame(self):
        '''This frame is the main canva with different sub-frames inside'''
        # Frame du titre principal
        header_frame = tk.Frame(self.container, bg='#1E1E1E')
        header_frame.pack(fill='both', anchor='n')

        tk.Label(header_frame, text=title, font='System 30 bold', fg='#fff', bg='#1E1E1E').pack(side='left', pady=(27, 5))
        tk.Label(header_frame, text=version, font='System 18 bold', fg='#fff', bg='#1E1E1E').pack(side='left', padx=10, pady=(37, 5))

        # Frame centrale qui sera changée au fur et à mesure de l'avancement
        self.main_frame = tk.Frame(self.container, bg='#ECECEC')
        self.main_frame.pack(fill='both', anchor='n', expand='yes')

        # Frame contenant le bouton d'affichage des logs
        log_frame = tk.Frame(self.container, bg='white')
        log_frame.pack(fill='both', side='bottom')
        tk.Label(log_frame, text='Emplacement des logs : {}'.format(logs_file), font='System 12 italic', bg='white').pack(side='left', padx=8, pady=8)
        tk.Button(log_frame, text='Afficher la console de logs', command=show_logs, highlightbackground='white').pack(side='right', padx=8, pady=8)

    def user_login_frame(self):
        '''Create a login frame to prevent everyone to use the application'''
        self.login_frame = tk.Label(self.main_frame)
        self.login_frame.pack(fill='both', side='top')

        # Title
        tk.Label(self.login_frame, text='Authentification nécessaire', font='System 16 bold').grid(row=0, column=0, sticky='w', pady=(5, 0))

        # Login and password fields
        self.log_user = tk.StringVar()
        tk.Label(self.login_frame, text='Login :').grid(row=1, column=0, sticky='w', padx=(180,10), pady=(60, 0))
        e1 = tk.Entry(self.login_frame, textvar=self.log_user, background='white', width=45)
        e1.grid(row=1, column=1, sticky='w', pady=(60, 0))
        e1.focus()

        self.log_pswd = tk.StringVar()
        tk.Label(self.login_frame, text='Mot de passe :').grid(row=2, column=0, sticky='w', padx=(180,10), pady=(3, 0))
        tk.Entry(self.login_frame, textvar=self.log_pswd, background='white', show='*', width=45).grid(row=2, column=1, sticky='w', pady=(3, 0))

        # Buttons
        tk.Button(self.login_frame, text='Quitter', command=root.destroy).grid(row=3, column=0, sticky='ew', padx=(180,10), pady=(3, 0))
        tk.Button(self.login_frame, text='Connexion', command=self.connect).grid(row=3, column=1, sticky='ew', pady=(3, 0))
        
    def show_config_frame(self):
        '''This frame displays the main configuration fields'''
        # MacOS reset title
        self.reset_title_frame = tk.Frame(self.main_frame)
        self.reset_title_frame.pack(fill='both', side='top')
        self.reset_title = tk.Label(self.reset_title_frame, text="Réinitialisation complète de MacOS", font='System 16 bold')
        self.reset_title.pack(side='left', padx=5, pady=5)

        # MacOS reset frame
        self.reset_frame = tk.Frame(self.main_frame)
        self.reset_frame.pack(fill='both', side='top', padx=5)

        # MacOS Installer Choice      
        text = tk.Label(self.reset_frame, text="Version macOS à réinstaller ({} recommandé) :".format(jamf["macos_last_version"]))
        text.grid(row=2, column=0, sticky='w', padx=10, pady=(30, 0))

        installers = search_local_installer(jamf['macos_last_version'])
        if installers is False:
            self.install_type = 'remote'
            log.info("Recherche d'installeurs distants dans la DB Jamf")
            installers = list_policies(self.json_headers, self.auth, jamf['policy_match_name'])
            if len(installers) == 0:
                self.error("Erreur", "Aucun installeur MacOS trouvé dans la DB Jamf !")
                self.resync()
        else:
            installers = [installers]
            self.install_type = 'local'
            
        self.installer = tk.StringVar()
        self.installer.set(installers[0])
        tk.OptionMenu(self.reset_frame, self.installer, *installers).grid(row=2, column=1, sticky='ew', pady=(30, 0))
        
        # Buttons
        self.reset_button_frame = tk.Frame(self.main_frame)
        self.reset_button_frame.pack(fill='both', side='top')
        tk.Button(self.reset_button_frame, text='Lancer la réinstallation', command=self.reset_computer).pack(fill='x', expand='yes', side='right', padx=5, pady=10)
        tk.Button(self.reset_button_frame, text='Annuler et quitter', command=root.destroy).pack(fill='x', expand='yes', side='right', padx=(5, 0), pady=10)

    def reset_computer(self):
        '''Delete the computer from Jamf DB and reinstall it from scratch'''
        try:
            confirm = tkMessageBox.askokcancel("Confirmation nécessaire", "Vous êtes sur le point de totalement réinstaller votre Mac.\nVoulez-vous continuer ?")

            if confirm is not True:
                log.info("Réinstallation annulée par l'utilisateur, redémarrage de l'application...")
                self.resync()
                return
            else:
                # Destroy the previous frames and create a new one with steps states
                self.reset_button_frame.destroy()
                self.reset_frame.destroy()
                self.reset_frame = tk.Frame(self.main_frame)
                self.reset_frame.pack(fill='both', side='top', padx=5)

                list_steps = [
                    ["check_download", "Téléchargement de l'installeur MacOS en attente..."],
                    ["check_del_adobe", 'Désactivation de la suite Adobe CC2019 en attente...'],
                    ["check_del_eset", "Suppression de l'antivirus ESET en attente..."],
                    ["check_upload_history", "Sauvegarde des infos Jamf vers SFTP en attente..."],
                    ["check_del_computer", 'Suppression de la base Jamf en attente...'],
                    ["check_launch_reset", "Réinitialisation de l'ordinateur en attente..."],
                    ["check_reboot", ""]
                ]

                step ={}
                
                i = 0
                for each_step in list_steps:
                    step[each_step[0]] = tk.Label(self.reset_frame, text=each_step[1])
                    step[each_step[0]].grid(row=i, column=0, sticky='w', padx=100, pady=(3, 0))
                    i += 1

                root.update()

                ### Launch the steps
                # If installer is 'remote', download it from Jamf. Else launch directly the reinstall
                if self.install_type == 'remote':
                    try:
                        chosen_policy = get_policy_details(self.json_headers, self.auth, self.installer.get())
                        trigger = chosen_policy['policy']['general']['trigger_other']
                        log.info("Téléchargement de l'installeur MacOS en cours, veuillez patienter...")
                        step['check_download'].configure(text="Téléchargement de l'installeur MacOS en cours...", fg="blue")
                        root.update()
                        if jamf_cmd('policy -event {}'.format(trigger)) is True:
                            log.info("Téléchargement terminé")
                            package_name = search_local_installer(jamf['macos_last_version'])
                            if package_name is not False:
                                step['check_download'].configure(text="Téléchargement terminé et validé", fg="green")
                            else:
                                raise Exception("Le paquet téléchargé n'a pas été trouvé dans la liste des applications")
                        else:
                            raise Exception("La commande Jamf de téléchargement du paquet a terminé en erreur")
                    except Exception as e:
                        log.error("Erreur pendant le téléchargement : {}".format(e), exc_info=True)
                        step['check_download'].configure(text="Téléchargement en erreur !", fg="red")
                        self.error("Erreur", "Une erreur a empêché le téléchargement de l'installeur MacOS ! Annulation...")
                        self.resync()
                        return
                else:
                    package_name = self.installer.get()
                    step['check_download'].configure(text="Installeur local sélectionné", fg="green")

                root.update()

                # Remove all adobe CC2019 apps with jamf policy
                if os.path.exists('/Applications/Adobe Premiere Pro CC 2019/Adobe Premiere Pro CC 2019.app/Contents/Info.plist'):
                    if jamf_cmd('policy -event uninstall_adobe') is True:
                        log.info("Applications Adobe supprimées avec succès")
                        step['check_del_adobe'].configure(text="Désactivation de la suite Adobe CC2019 : OK", fg="green")
                    else:
                        step['check_del_adobe'].configure(text="Désactivation de la suite Adobe CC2019 : Erreur", fg="red")
                        log.error("Une erreur a empêché la suppression des applications Adobe !")
                else:
                    step['check_del_adobe'].configure(text="Désactivation de la suite Adobe CC2019 : Non installé", fg="green")
                    log.error("Adobe CC2019 n'existe pas sur cette machine")

                root.update()

                # Remove ESET antivirus app with jamf policy
                if jamf_cmd('policy -event uninstall_eset') is True:
                    log.info("Application antivirus ESET supprimée avec succès")
                    step['check_del_eset'].configure(text="Suppression de l'antivirus ESET : OK", fg="green")
                else:
                    step['check_del_eset'].configure(text="Suppression de l'antivirus ESET : Erreur", fg="red")
                    log.error("Une erreur a empêché la suppression de l'application antivirus ESET !")
                
                root.update()

                # Upload the computer history to our SFTP server
                if upload_history(self.json_headers, self.auth, self.my_id, self.my_serial, self.my_name) is True:
                    step['check_upload_history'].configure(text="Sauvegarde des infos Jamf vers SFTP : OK", fg="green")
                else:
                    step['check_upload_history'].configure(text="Sauvegarde des infos Jamf vers SFTP  : Erreur", fg="red")
                    log.error("Une erreur a empêché la sauvegarde des infos Jamf vers FTP !")
                
                root.update()

                # Delete this computer from the Jamf DB to prevent conflicts
                if delete_computer(self.my_id, self.auth) is True:
                    log.info("Mac supprimé de la base données Jamf avec succès")
                    step['check_del_computer'].configure(text="Suppression de la base Jamf : OK", fg="green")
                    root.update()
                else:
                    step['check_del_computer'].configure(text="Suppression de la base Jamf : Erreur", fg="red")
                    self.error("Erreur", "Une erreur a empêché la suppression du Mac de la DB Jamf ! Merci de contacter le support IP-Echanges")
                    self.resync()
                    return

                # Launch the reinstall command
                try:
                    reset_command = threading.Thread(target=launch_reset, args=(package_name,))
                    reset_command.start()
                    step['check_launch_reset'].configure(text="Lancement de la réinstallation : OK", fg="green")
                    step['check_reboot'].configure(text="Redémarrage en cours, veuillez patientier...", fg="blue")
                    root.update()
                    log.info("La procédure de réinstallation est lancée, cliquez sur OK pour autoriser le redémarrage.")
                    show_jamfhelper()
                    
                except Exception as e:
                    log.error("Erreur pendant la réinstallation : {}".format(e))
                    step['check_launch_reset'].configure(text="Lancement de la réinstallation : Erreur", fg="red")
                    root.update()
                    text = "Attention !\nLa commande de réinitialisation ne s'est pas effectuée correctement ! Merci de contacter le support IP-Echanges"
                    self.error("Erreur pendant la réinitialisation", text)
                    self.resync()
                    return
        except Exception as e:
            log.error("Erreur dans la fonction reset_computer : {}".format(e), exc_info=True)
            self.resync()
            return
        

    
###########################################################################
### Start the main application
###########################################################################
if __name__ == '__main__':
    log.info('--- Lancement de {}, {} ---'.format(title, version))

    # Import downloaded libraries
    try:
        import requests
    except Exception as e:
        log.error("*** Erreur *** Impossible d'importer la librairie Python requests.\nContacter le support IP-Echanges.\n\nRaison : {}".format(e))
        sys.exit(1)

    try:
        import AppKit
    except Exception as e:
        log.error("*** Erreur *** Impossible d'importer la librairie Python AppKit.\nContacter le support IP-Echanges.\n\nRaison : {}".format(e))
        sys.exit(1)
    
    try:
        import pysftp
    except Exception as e:
        log.error("*** Attention *** Impossible d'importer la librairie Python pysftp.\nCeci empêchera le script de créer une sauvegarde vers un serveur SFTP distant.\n\nRaison : {}".format(e))
        sys.exit(1)
        
    # Import caffeine and prevent mac from sleeping    
    try:
    	import caffeine
        caffeine.on(display=True)
        log.info("Module Caffeine activé, mise en veille interdite")
    except:
    	log.warning("Impossible d'activer le module caffeine, le Mac risque de passer en mode veille en cours d'installation")

    # Defining main API variables
    try:
        # Defining variables from Jamf
        jamf = {
            'url_jamf':sys.argv[4],
            'policy_match_name':sys.argv[5],
            'sftp_address':sys.argv[6],
            'sftp_credentials':sys.argv[7],
            'macos_last_version':sys.argv[8],
            'autologon':sys.argv[9],
            'api_user':sys.argv[10],
            'api_pswd':sys.argv[11],
            }
        log.info('Using jamf arguments as main variables')
    except:
        # Jamf testing parameters
        jamf = {
            'url_jamf':"YOUR_JAMF_URL",
            'policy_match_name':"YOUR_CUSTOM_TRIGGER",
            'sftp_address':'YOUR_SFTP_ADDRESS:PORT',
            'sftp_credentials':'USERNAME:PASSWORD',
            'macos_last_version':'10.14.6',
            'autologon':'non',
            'api_user':'USERNAME',
            'api_pswd':'PASSWORD',
            }
        log.info('Using test parameters as main variables')

    # Common variables
    sftp_root = '/'

    # Kill Self Service app
    os.system('killall "Self Service"')
    
    # Launch Tkinter app
    root = tk.Tk()
    app = JamfOneClickReinstall(root)
    AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    root.mainloop()
