class Provider():

    def __init__(self):
        pass

    def getInstance(self, provider):

        classname = provider + 'CloudProvider'

        providerModule = __import__('ec2spotmanager.CloudProvider.%s' % classname, fromlist=[classname])
        providerClass = getattr(providerModule, classname)

        return providerClass()
