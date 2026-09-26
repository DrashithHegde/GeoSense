#include <bits/stdc++.h>
using namespace std;

using ll = long long;
using ull = unsigned long long;

const ll INF = 1e18;
const int MOD = 1e9 + 7;

void solve() {
    int n;
    cin>>n;
    vector<int> a(n),pos(n+1);
    for (int i=0;i<n;i++){
        cin>>a[i];
        pos[a[i]]=i;
    }

    int start;
    if (n%2) start=2;
    else start=1;
    for (int i=start;i<n;i+=2) {
        if (pos[i]%2==pos[i+1]%2) {
            cout<<"NO"<<endl;
            return;
        }
    }
    cout<<"YES"<<endl;

}

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    int t;
    cin >> t;

    while (t--) {
        solve();
    }

    return 0;
}