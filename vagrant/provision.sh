#!/usr/bin/env bash
# Aprovisionamiento como root: escritorio, KiCad 9, Node 20, Claude Code.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# Sin preguntas por archivos de configuración ya modificados en la box
APT_OPTS=(-y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)

# Reparar una corrida anterior interrumpida a medias
dpkg --configure -a || true

apt-get update
apt-get install "${APT_OPTS[@]}" software-properties-common curl ca-certificates git build-essential python3-pip

# Escritorio liviano (XFCE) + guest additions para 3D/resolución
apt-get install "${APT_OPTS[@]}" xfce4 xfce4-terminal lightdm lightdm-gtk-greeter virtualbox-guest-x11
# Sin bloqueo de pantalla: en la VM solo estorba (queda trabado en la pantalla de LightDM)
apt-get remove "${APT_OPTS[@]}" light-locker light-locker-settings || true
systemctl set-default graphical.target

# KiCad desde el PPA oficial (https://www.kicad.org/download/linux-distros/).
# El MCP (kicad-mcp 2.8.x) escribe esquemáticos en formato KiCad 10; KiCad 9 no los abre.
KICAD_VERSION="${KICAD_VERSION:-10.0}"
if ! command -v kicad >/dev/null; then
  for intento in 1 2 3 4 5; do
    add-apt-repository -y "ppa:kicad/kicad-${KICAD_VERSION}-releases" && break
    echo "add-apt-repository falló (intento $intento), reintentando..."; sleep 10
  done
  apt-get update
  apt-get install "${APT_OPTS[@]}" kicad
fi

# Node 20 (NodeSource)
if ! node -v 2>/dev/null | grep -q '^v20'; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install "${APT_OPTS[@]}" nodejs
fi

# Claude Code (el login lo hace el usuario a mano)
if ! command -v claude >/dev/null; then
  npm install -g @anthropic-ai/claude-code
fi

# Autologin del usuario vagrant en el escritorio (LightDM exige el grupo autologin)
groupadd -f -r autologin
gpasswd -a vagrant autologin
mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/50-autologin.conf <<'EOF'
[Seat:*]
autologin-user=vagrant
autologin-user-timeout=0
autologin-session=xfce
user-session=xfce
EOF
