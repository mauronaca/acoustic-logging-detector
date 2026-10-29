# Laboratorio KiCad + MCP + Claude Code (ver SPEC.md, sección "Laboratorio").
# Todo corre dentro de la VM; el repo se comparte con Windows en /home/vagrant/proyecto.
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  config.vm.hostname = "kicad-lab"
  # VirtualBox sobre el hipervisor de Windows (NEM) arranca lento.
  config.vm.boot_timeout = 900

  # Carpeta compartida con Windows (decisión explícita: se resigna parte del aislamiento
  # del SPEC a cambio de pasar archivos directo). Ruta relativa al Vagrantfile.
  config.vm.synced_folder ".", "/vagrant", disabled: true
  config.vm.synced_folder ".", "/home/vagrant/proyecto", type: "virtualbox"

  config.vm.provider "virtualbox" do |vb|
    vb.name = "kicad-lab"
    vb.gui = true
    vb.memory = 4096
    vb.cpus = 2
    # Sin esto el kernel se cuelga al arrancar con VirtualBox sobre el hipervisor de Windows.
    vb.customize ["modifyvm", :id, "--paravirt-provider", "none"]
    vb.customize ["modifyvm", :id, "--vram", "128"]
    vb.customize ["modifyvm", :id, "--graphicscontroller", "vmsvga"]
    vb.customize ["modifyvm", :id, "--accelerate3d", "off"]
    # PS/2 emulado pierde clicks y teclas sobre el hipervisor de Windows: usar dispositivos USB.
    vb.customize ["modifyvm", :id, "--usb-xhci", "on"]
    vb.customize ["modifyvm", :id, "--mouse", "usbtablet"]
    vb.customize ["modifyvm", :id, "--keyboard", "usb"]
    vb.customize ["modifyvm", :id, "--clipboard-mode", "bidirectional"]
    vb.customize ["modifyvm", :id, "--draganddrop", "disabled"]
  end

  config.vm.provision "sistema", type: "shell", path: "vagrant/provision.sh", privileged: true,
    env: { "KICAD_VERSION" => ENV.fetch("KICAD_VERSION", "10.0") }
  config.vm.provision "usuario", type: "shell", path: "vagrant/provision-user.sh", privileged: false
end
