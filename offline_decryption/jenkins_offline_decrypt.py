#!/usr/bin/env python3
import sys
import re
import base64
import os.path
from hashlib import sha256
from Crypto.Cipher import AES


# configure this to your liking
secret_title_list = [ 'apiToken', 'password', 'privateKey', 'passphrase', 'secret', 'secretId', 'value', 'defaultValue', 'apiToken']

decryption_magic = b'::::MAGIC::::'


# USAGE ########################################################################
def usage():
    name = '\t' + os.path.basename(sys.argv[0])
    print('Usage:')
    print(name + ' <jenkins_base_path>')
    print('or:')
    print(name + ' <master.key> <hudson.util.Secret> [credentials.xml]')
    print('or:')
    print(name + ' -i <path> (interactive mode)')
    sys.exit(1)


# RECOVER CONFIDENTIALITY KEY ##################################################
def get_confidentiality_key(master_key_path, hudson_secret_path):

    # the master key is random bytes stored in text
    with open(master_key_path, 'r') as f:
        master_key = f.read().encode('utf-8')

    # the hudson secret is bytes encrypted using a key derived from the master key
    with open(hudson_secret_path, 'rb') as f:
        hudson_secret = f.read()

    # sanitize keys if copy or base64 introduced a newline
    if len(master_key)%2 != 0 and master_key[-1:] == b'\n':
        master_key = master_key[:-1]
    if len(hudson_secret)%2 != 0 and hudson_secret[-1:] == b'\n':
        hudson_secret = hudson_secret[:-1]

    return decrypt_confidentiality_key(master_key, hudson_secret)


def decrypt_confidentiality_key(master_key, hudson_secret):

    # the master key is hashed and truncated to 16 bytes due to US restrictions
    derived_master_key = sha256(master_key).digest()[:16]

    # the hudson key is decrypted using this derived key
    cipher_handler = AES.new(derived_master_key, AES.MODE_ECB)
    decrypted_hudson_secret = cipher_handler.decrypt(hudson_secret)

    # check if the key contains the magic
    if decryption_magic not in decrypted_hudson_secret:
        return None

    # the hudson key is the first 16 bytes for AES128
    return decrypted_hudson_secret[:16]


# DECRYPTION ###################################################################
# old secret encryption format in jenkins is plain AES ECB
def decrypt_secret_old_format(encrypted_secret, confidentiality_key):
    cipher_handler = AES.new(confidentiality_key, AES.MODE_ECB)
    decrypted_secret = cipher_handler.decrypt(encrypted_secret)

    if not decryption_magic in decrypted_secret:
        return None

    return decrypted_secret.split(decryption_magic)[0]


# new encryption format in jenkins is AES CBC
def decrypt_secret_new_format(encrypted_secret, confidentiality_key):
    iv = encrypted_secret[9:9+16] # skip version + iv and data lengths
    cipher_handler = AES.new(confidentiality_key, AES.MODE_CBC, iv)
    decrypted_secret = cipher_handler.decrypt(encrypted_secret[9+16:])

    # remove PKCS#7 padding
    padding_value = decrypted_secret[-1]
    if padding_value > 16:
        return decrypted_secret

    secret_length = len(decrypted_secret) - padding_value

    return decrypted_secret[:secret_length]


def decrypt_secret(encoded_secret, confidentiality_key):
    if encoded_secret is None:
        return None

    try:
        encrypted_secret = base64.b64decode(encoded_secret)
    except base64.binascii.Error as error:
        print('Failed base64 decoding the input with error: ' + str(error))
        print('If your input was quite large and exceeded the terminal\'s ' +
              '4096 char input limit then you might want to increase it using' +
              ' stty -icanon')
        print(encoded_secret)
        return None

    if encrypted_secret[0] == 1:
        return decrypt_secret_new_format(encrypted_secret, confidentiality_key)
    else:
        return decrypt_secret_old_format(encrypted_secret, confidentiality_key)



# FILE DECRYPTION MODE #########################################################
def decrypt_credentials_file(credentials_file, confidentiality_key):
    with open(credentials_file, 'r') as f:
        data = f.read()

    # old password storage format just contains a b64 value whereas new format
    # dictates the secret should be inside curly braces, so find all we can and
    # then remove duplicates
    secrets = []
    for secret_title in secret_title_list:
        secrets += re.findall(secret_title + '>\{?(.*?)\}?</' + secret_title, data)
    secrets += re.findall('>{([a-zA-Z0-9=+/]*)}</', data)
    secrets = list(set(secrets))

    for secret in secrets:
        try:
            decrypted_secret = decrypt_secret(secret, confidentiality_key)
            if decrypted_secret != b'':
                print(decrypted_secret.decode('utf-8'))
        except Exception as e:
            print(e)


# INTERACTIVE MODE #############################################################
def run_interactive_mode(confidentiality_key):
    while 1:
        secret = input('Encrypted secret: ')
        if not secret:
           continue
        else:
            try:
                decrypted_secret = decrypt_secret(secret, confidentiality_key)
                print(decrypted_secret.decode('utf-8'))
            except Exception as e:
                print(e)
                print(decrypted_secret)


# MAIN #########################################################################
credentials_file = ''

# parse arguments
if len(sys.argv) > 4 or len(sys.argv) < 2:
    usage()
    exit(1)

if sys.argv[1] == '-i':
    base_path = sys.argv[2]
    if not os.path.isdir(base_path):
        usage()
        exit(1)
    master_key_file = base_path + '/secrets/master.key'
    hudson_secret_file = base_path + '/secrets/hudson.util.Secret'
    if (not os.path.exists(master_key_file) or
        not os.path.exists(hudson_secret_file)):
        print('Failed finding required files where I expected them')
        exit(1)
elif len(sys.argv) == 2:
    base_path = sys.argv[1]
    if not os.path.isdir(base_path):
        usage()
        exit(1)
    credentials_file = base_path + '/credentials.xml'
    master_key_file = base_path + '/secrets/master.key'
    hudson_secret_file = base_path + '/secrets/hudson.util.Secret'
    if (not os.path.exists(credentials_file) or not os.path.exists(master_key_file) or
        not os.path.exists(hudson_secret_file)):
        print('Failed finding required files where I expected them')
        exit(1)
else:
    master_key_file = sys.argv[1]
    hudson_secret_file = sys.argv[2]
    if len(sys.argv) == 4:
        credentials_file = sys.argv[3]


confidentiality_key = get_confidentiality_key(master_key_file, hudson_secret_file)
if not confidentiality_key:
    print('Failed decrypting confidentiality key')
    exit(1)

if credentials_file:
    decrypt_credentials_file(credentials_file, confidentiality_key)
else:
    run_interactive_mode(confidentiality_key)
