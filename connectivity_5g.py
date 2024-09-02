import subprocess
import threading
import time
import subprocess
import json
import time

TIME_DELAY = 0.5
SIGNAL_STRENGTH_TRHRESHOLD = 20
RETRIES_WITHOUT_BEARER = 10
RETRIES_WITHOUT_PLMN = 3
TIME_DELAY_TO_RESET = 10

HOME_PLMN = "00101"
PLMN_LIST_ALLOWED = ["00101", "99970"]
APN = "internet"
IP_TYPE = "ipv4"

modem_info = None
modem_index = None

def run_mmcli_command(command):
    result = subprocess.run(command, capture_output=True, text=True)

    if result.stderr:
        return None
    
    return json.loads(result.stdout)

def get_modem_index():
    result = run_mmcli_command(['mmcli', '-L', '-J'])
    result = result.get("modem-list", [])

    for modem in result:
        return modem.split('/')[-1]
    return None

def get_active_bearer_index(modem_index):
    result = run_mmcli_command(['mmcli', '-m', modem_index, '-J'])

    result = result.get('modem', [])
    if result == None:
        return None
    result = result.get('generic', [])
    if result == None:
        return None
    result = result.get('bearers', [])
    if result == None:
        return None

    for bearer in result:
        #print(f"Bearer: {bearer}")
        bearer_index = bearer.split('/')[-1]
        return bearer_index
        
    return None

def is_bearer_connected(bearer_index):
    bearer_result = run_mmcli_command(['mmcli', '-b', bearer_index, '-J'])
    bearer_result = bearer_result.get("bearer", [])
    if bearer_result['status'] == 'connected':
        return bearer_index
    
def check_signal_strength(modem_index):
    result = run_mmcli_command(['mmcli', '-m', modem_index, '-J'])
    result = result.get('modem', [])
    if result == None:
        return None
    result = result.get('generic', [])
    if result == None:
        return None
    if 'signal-quality' in result:
        quality = int(result['signal-quality']['value'])
        return quality
    return None

def check_connectivity():
    result = subprocess.run(['ping', '-c', '1', '8.8.8.8'], capture_output=True)
    return result.returncode == 0

def get_plmn_connected(modem_index):
    result = run_mmcli_command(['mmcli', '-m', modem_index, '-J'])

    result = result.get('modem', [])
    if result == None:
        return None
    result = result.get('3gpp', [])
    if result == None:
        return None
    if result['packet-service-state'] == 'attached':
        return result['operator-code']
    
    return None

def is_interface_configured():
    result = subprocess.run(['ip', 'addr', 'show', 'wwan0'], capture_output=True, text=True)
    print(f"is_configured: {'inet ' in result.stdout}")
    return 'inet ' in result.stdout

def reconfigure_interface():
    result = subprocess.run(['sudo', 'udhcpc', '-n', '-q', '-f', '-i', 'wwan0', '-t', '5', '-T', '1'])
    print(result)

def reset_interface():
    subprocess.run(['sudo', 'ip', 'link', 'set', 'wwan0', 'down'])
    subprocess.run(['sudo', 'ip', 'link', 'set', 'wwan0', 'up'])


def connect_modem(modem_index):
    result = subprocess.run(['mmcli', '-m', modem_index, f'--simple-connect=apn={APN},ip-type={IP_TYPE}', f'--create-bearer=operator-id={TIME_DELAY}', '-J'], capture_output=True, text=True)

    if result.stdout == "successfully connected the modem\n":
        return True
    else:
        return False

def register_modem(modem_index):
    result = subprocess.run(['mmcli', '-m', modem_index, f'--3gpp-register-in-operator={HOME_PLMN}', '-J'], capture_output=True, text=True)
    #print(result)
    if "successfully registered the modem" in result.stdout:
        return True
    elif "Cannot register modem: modem is connected" in result.stderr:
        return True
    else:
        return False

def get_modem_info():

    global modem_info
    global modem_index

    
    while True:

        modem_index = get_modem_index()

        if modem_index is None:
            modem_info = None
            print(f"No modem found. Retrying in {TIME_DELAY_TO_RESET} seconds.")
            time.sleep(TIME_DELAY_TO_RESET)
            continue

        result = run_mmcli_command(['mmcli', '-J', '-m', modem_index])
        result = result.get('modem', [])
        
        if result:
            modem_info = result
        else:
            modem_info = None

        time.sleep(TIME_DELAY)

def reset_modem(modem_index):
    subprocess.run(['mmcli', '-m', modem_index, '--reset', '-J'])

def main():

    retries_without_bearer = 0
    retries_without_plmn = 0
    plmn_connected = None
    is_connected = False

    info_thread = threading.Thread(target=get_modem_info)
    info_thread.daemon = True
    info_thread.start()

    global modem_info
    global modem_index
    
    # waiting for info_thread
    print(f"starting service")
    time.sleep(TIME_DELAY)

    while True:

        while modem_index != None and modem_info != None:
            
            is_modem_regitered = register_modem(modem_index)
            if not is_modem_regitered:
                print(f"device wasn't registered")
                time.sleep(TIME_DELAY)
                continue

            is_modem_connected = connect_modem(modem_index)
            if not is_modem_connected:
                print(f"device wasn't connected")
                time.sleep(TIME_DELAY)
                continue
            
            bearer_index = get_active_bearer_index(modem_index)

            if bearer_index is None:
                print("No active bearer found. Attempting to connect.")
                if not connect_modem(modem_index):
                    
                    if retries_without_bearer >= RETRIES_WITHOUT_BEARER:
                        retries_without_bearer = 0
                        print(f"Max retries without bearer has been reached. Restarting device and retrying in {TIME_DELAY_TO_RESET} seconds.")
                        reset_modem(modem_index)
                        time.sleep(TIME_DELAY_TO_RESET)
                        continue
                        
                    else:
                        retries_without_bearer += 1
                        print(f"It was not possible connect to {HOME_PLMN}. Retries: {retries_without_bearer}")
                        print(f"Retrying in {TIME_DELAY} seconds.")
                        time.sleep(TIME_DELAY)
                        continue

                else:

                    bearer_index = get_active_bearer_index(modem_index)
                    is_b_connected = is_bearer_connected(bearer_index)

                    if bearer_index is None or not is_b_connected:
                        if retries_without_bearer >= RETRIES_WITHOUT_BEARER:
                            retries_without_bearer = 0
                            print(f"Max retries without bearer has been reached. Restarting device")
                            print(f"Retrying in {TIME_DELAY_TO_RESET} seconds.")
                            reset_modem(modem_index)
                            time.sleep(TIME_DELAY_TO_RESET)
                            continue
                        else:
                            retries_without_bearer += 1
                            print(f"It was not possible connect to {HOME_PLMN}. Retries: {retries_without_bearer}")
                            print(f"Retrying in {TIME_DELAY} seconds.")
                            time.sleep(TIME_DELAY)
                            continue
                    else:
                        print(f"Bearer {bearer_index} is connected.")
                        plmn_connected = get_plmn_connected(modem_index)
                        retries_without_bearer = 0

            print(f"Modem index: {modem_index}, Active Bearer index: {bearer_index}")

            # check if there is roaming
            new_plmn = get_plmn_connected(modem_index)
            print(f"new_plmn: {new_plmn}")
            if new_plmn == None and plmn_connected == None:
                if retries_without_plmn >= RETRIES_WITHOUT_PLMN:
                    retries_without_plmn = 0
                    print(f"Max retries without bearer has been reached.")
                    print(f"Restarting device and retrying in {TIME_DELAY_TO_RESET} seconds.")
                    reset_modem(modem_index)
                    time.sleep(TIME_DELAY_TO_RESET)
                    continue
                    
                else:
                    retries_without_plmn += 1
                    print(f"NEWPLMN and OLDPLMN are None. It was not possible connect to {HOME_PLMN}. Retries: {retries_without_plmn}")
                    print(f"Retrying in {TIME_DELAY} seconds.")
                    print("Trying to connect again...")
                    connect_modem(modem_index)
            elif plmn_connected != new_plmn:
                print(f"The serving system of the modem has been changed. Old PLMN: {plmn_connected} - New PLMN: {new_plmn}")
                print("It's neccesary to reconfigure new bearer")
                bearer_index = None
                is_connected = False
                plmn_connected = new_plmn
                reconfigure_interface()
                print("Trying to connect again...")
                connect_modem(modem_index)
                continue

            

            signal_strength = check_signal_strength(modem_index)
            if signal_strength is None:
                print("Could not retrieve signal strength.")
            elif signal_strength < SIGNAL_STRENGTH_TRHRESHOLD:  # Adjust the threshold as needed
                print(f"Low signal strength detected: {signal_strength}%")
                if not check_connectivity():
                    print("Connectivity lost. Reconfiguring interface.")
                    reconfigure_interface()
                else:
                    print("Connectivity is still up despite low signal strength.")
            else:
                print(f"Signal strength is sufficient: {signal_strength}%")
            
            if not is_interface_configured():
                print("Interface wwan0 is not configured. Reconfiguring.")
                reconfigure_interface()
            else:
                print("Interface wwan0 is already configured.")
            
            time.sleep(TIME_DELAY)  # Wait for a TIME_DELAY before checking again
        
        print(f"getting modem info")
        time.sleep(TIME_DELAY)  # Wait for a TIME_DELAY before checking again



if __name__ == "__main__":
    main()
