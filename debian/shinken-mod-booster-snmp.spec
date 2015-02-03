Name:		shinken-mod-booster-snmp
Version:	2.0
Release:	1
Summary:	Shinken Module SNMP Booster

Group:		Network
License:	AGPLv3+
URL:		https://github.com/savoirfairelinux/mod-booster-snmp
Source0:	%{name}_%{version}.orig.tar.gz

BuildArch:  noarch

Requires:	shinken-common >= 2.0

%description
Shinken Booster SNMP module

%prep
%setup -q


%build


%install
rm -rf %{buildroot}/*

install -d %{buildroot}/usr/share/pyshared/shinken/modules/booster-snmp
cp -r module/* %{buildroot}/usr/share/pyshared/shinken/modules/booster-snmp 

install -d %{buildroot}/usr/share/doc/%{name}
cp -r doc/* %{buildroot}/%{_docdir}/%{name}


install -d %{buildroot}/etc/shinken/modules
install -pm0755 etc/modules/* %{buildroot}/etc/shinken/modules


%files
/usr/share/pyshared/shinken/modules/booster-snmp
%config(noreplace) %{_sysconfdir}/shinken/modules/

%doc %{_docdir}/%{name}/*


%changelog
* Tue Feb 03 2015 Sébastien Coavoux <sebastien.coavoux@savoirfairelinux.com> 2.0-1
- Initial Package
