include $(TOPDIR)/rules.mk
PKG_NAME:=hass-openwrt-vpn-controller
PKG_VERSION:=0.2.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT
PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)
include $(INCLUDE_DIR)/package.mk

define Package/$(PKG_NAME)
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Restricted autonomous Podkop VPN controller
  DEPENDS:=+ucode +ucode-mod-fs +ucode-mod-uci +ucode-mod-ubus +ucode-mod-uloop +rpcd +curl +ca-bundle +jq +sing-box +podkop +ip-full +nftables-json +uhttpd +uhttpd-mod-ubus +libustream-mbedtls
endef

define Package/$(PKG_NAME)/conffiles
/etc/vpn-controller/config.json
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) ./src/io.c $(PKG_BUILD_DIR)/
endef

define Build/Compile
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror -o $(PKG_BUILD_DIR)/vpn-controller-io $(PKG_BUILD_DIR)/io.c $(TARGET_LDFLAGS)
endef

define Package/$(PKG_NAME)/install
	$(CP) ./files/* $(1)/
	$(INSTALL_DIR) $(1)/usr/share/rpcd/acl.d $(1)/usr/share/vpn-controller $(1)/usr/libexec $(1)/usr/share/licenses/$(PKG_NAME)
	$(INSTALL_DATA) ./rpcd-acl/hass-openwrt-vpn.json $(1)/usr/share/rpcd/acl.d/
	$(INSTALL_DATA) ./podkop-0.7.23.sha256.json $(1)/usr/share/vpn-controller/podkop-hashes.json
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/vpn-controller-io $(1)/usr/libexec/
	$(INSTALL_DATA) ./LICENSE $(1)/usr/share/licenses/$(PKG_NAME)/LICENSE
	chmod 0755 $(1)/usr/share/vpn-controller/vpn-controller.init $(1)/usr/sbin/vpn-controller.uc $(1)/usr/libexec/vpn-controller-podkop-render
	chmod 0700 $(1)/etc/vpn-controller
	chmod 0600 $(1)/etc/vpn-controller/config.json
endef

$(eval $(call BuildPackage,$(PKG_NAME)))
