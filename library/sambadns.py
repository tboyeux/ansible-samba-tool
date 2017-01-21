#!/usr/bin/python2

# DON'T FORGET TO CHANGE BACK TO PYTHON WITHOUT 2$


from ansible.module_utils.basic import AnsibleModule
try:
    import samba
except ImportError:
    HAS_SAMBA = False
else:
    HAS_SAMBA = True

class dnsCommand():
    def __init__(self, module):
        self.module = module
        self.username = module.params['username']
        self.password = module.params['password']
        self.credopts = ["--username=" + self.username]
        self.credopts.append("--password=" + self.password) 

    def create(self, actionType, dnsServer, dnsZone=None, rName=None, rType=None, rData=None): 
        # Check that action is supported by samba-tool dns
        if actionType.lower() not in ('add', 'delete', 'zonecreate', 'zonedelete', 'serverinfo'):
            raise RuntimeError('%s option is not supported by "samba-tool dns".' % actionType)
        
        cmd = [self.module.get_bin_path('samba-tool', True)]
        cmd.append('dns')
        cmd.append(actionType) 
        cmd.append(dnsServer)
        if dnsZone is not None: cmd.append(dnsZone)
        if rName is not None: cmd.append(rName)
        if rType is not None: cmd.append(rType)
        if rData is not None: cmd.append(rData)
        self.cmd = cmd + self.credopts
          
    def execute(self, use_unsafe_shell=False, data=None, obey_checkmode=True):        
        if self.module.check_mode and obey_checkmode:
            self.module.debug('In check mode, would have run: "%s"' % self.cmd)
            return (0, '', '')
        else:
            # cast all args to strings ansible-modules-core/issues/4397
            cmd = [str(x) for x in self.cmd]
            return self.module.run_command(cmd, use_unsafe_shell=use_unsafe_shell, data=data)      
         
class dnsServer():
    
    def __init__(self, module):
        self.module = module
        self.dnsServer = module.params['dnsServer']
    
    # Check connection with the server through a serverinfo command
    def check_connection(self):
        cmd = dnsCommand(self.module)
        cmd.create('serverinfo', self.dnsServer)
        return cmd.execute(obey_checkmode=False)

class dnsRecord():    
    
    def __init__(self, module):
        self.module = module
        self.dnsServer = module.params['dnsServer']
        self.dnsZone = module.params['dnsZone']    
        self.rName = module.params['rName']
        self.rType = module.params['rType']
        self.rData = module.params['rData']
  
    # Create a DNS record        
    def add_record(self):
        cmd = dnsCommand(self.module)
        cmd.create('add', self.dnsServer, self.dnsZone, self.rName, \
            self.rType, self.rData)
        return cmd.execute()
    
    # Delete a DNS record
    def delete_record(self):
        cmd = dnsCommand(self.module)
        cmd.create('delete', self.dnsServer, self.dnsZone, self.rName, \
            self.rType, self.rData)
        return cmd.execute(cmd)
          
    
    def get_ptr_zone(self):
        # Reverse the IP address and remove the first digits        
        reverse_zone = self.rData.split('.')[::-1][1:]        
        return '.'.join(reverse_zone) + '.in-addr.arpa'
    
    # Create a PTR record        
    def create_ptr(self):
        cmd = dnsCommand(self.module)
        cmd.create('add', self.dnsServer, self.get_ptr_zone(), \
            self.rData.split('.')[-1], 'PTR', self.rName)
        return cmd.execute()  
  
    # Delete a PTR record        
    def delete_ptr(self):
        cmd = dnsCommand(self.module)
        cmd.create('delete', self.dnsServer, self.get_ptr_zone(), \
            self.rData.split('.')[-1], 'PTR', self.rName)
        return cmd.execute()   
    
class dnsZone():
    # Create a DNS zone. Samba service needs to be restarted after zone creation
    
    def __init__(self, module):
        self.module = module
        self.dnsServer = module.params['dnsServer']
        self.dnsZone = module.params['dnsZone']    
    
    def create_zone(self):
        cmd = dnsCommand(self.module)
        cmd.create('zonecreate', self.dnsServer, self.dnsZone)
        (rc, out, err) = cmd.execute(cmd)
                    
        if 'WERR_DNS_ERROR_ZONE_ALREADY_EXISTS' in err:
            err = 'Zone %s already exists' % (self.dnsZone)
        
        return (rc, out, err) 
    
    # Delete a DNS zone. Samba service needs to be restarted after zone deletion
    
    def delete_zone(self):
        cmd = dnsCommand(self.module)
        cmd.create('zonedelete', self.dnsServer, self.dnsZone)
        (rc, out, err) = cmd.execute(cmd)
                    
        if 'WERR_DNS_ERROR_ZONE_DOES_NOT_EXIST' in err:
            err = 'Zone %s does not exist' % (self.dnsZone)
        
        return (rc, out, err)
   
             
def main():

    module = AnsibleModule(
        argument_spec=dict(
            state=dict(default='present', choices=['present', 'absent'], type='str'),
            function=dict(required=True, choices=['record', 'zone'], type='str'),
            # following options are specific to dns function
            dnsServer=dict(required=True, default=None, type='str'),
            dnsZone=dict(required=True, default=None, type='str'),
            rName=dict(default=None, type='str'),
            rType=dict(default='A', choices=['A', 'AAAA', 'PTR', 'CNAME', 'MX', 'SRV', 'TXT']),
            rData=dict(default=None, type='str'),
            username=dict(default=None, type='str'),
            password=dict(default=None, type='str')
        ),
        supports_check_mode=True,
        required_if=[
            ['function', 'record', ['rName', 'rData']],
        ]
    )
    
    if not HAS_SAMBA:
        module.fail_json(
            msg='The `samba` module is not importable. Check the requirements.'
        )
    
    state = module.params['state']
    function = module.params['function']
   
    result = {}   
            
    # TODO: data validation : dnsServer, dnsZone, rName, rData
    
    # Check connection
    server = dnsServer(module)
    (rc, out, err) = server.check_connection()
    if rc == 0 and module.check_mode:
        result['connection'] = 'OK'
    elif rc is not None and rc != 0 :
        result['changed'] = False
        result['msg'] = err
        module.fail_json(**result)        
    
    
    if function == 'record':
        record = dnsRecord(module)
        
        if state == 'present':
            (rc, out, err) = record.create_ptr() if record.rType == 'PTR' \
                else record.add_record()    

        elif state == 'absent':
            (rc, out, err) = record.delete_ptr() if record.rType == 'PTR' \
                else record.delete_record()
                
        if rc == 0:
            result['changed'] = True
            result['stdout'] = out
            module.exit_json(**result)

        elif rc is not None and rc != 0:
            result['changed'] = False
            result['msg'] = err
            module.fail_json(**result)         
            
    elif function == 'zone':
        zone = dnsZone(module)
        
        if state == 'present':
            (rc, out, err) = zone.create_zone()
        elif state == 'absent':
            (rc, out, err) = zone.delete_zone()
        
        if rc == 0:
            result['changed'] = True
            result['stdout'] = out
            module.exit_json(**result)

        elif rc is not None and rc != 0:
            result['changed'] = False          
            result['msg'] = err
            module.fail_json(**result)  
        
        
if __name__ == '__main__':
    main()
    
