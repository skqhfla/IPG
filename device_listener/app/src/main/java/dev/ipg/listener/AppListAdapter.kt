package dev.ipg.listener

import android.graphics.drawable.Drawable
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.CheckBox
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

data class AppItem(
    val packageName: String,
    val label: String,
    val icon: Drawable,
    val isSystem: Boolean,
)

class AppListAdapter(
    private val onSelectionChanged: () -> Unit,
) : RecyclerView.Adapter<AppListAdapter.VH>() {

    private var allItems: List<AppItem> = emptyList()
    private var visibleItems: List<AppItem> = emptyList()
    private val selected: MutableSet<String> = mutableSetOf()
    private var searchQuery: String = ""

    fun setAllItems(items: List<AppItem>) {
        allItems = items
        rebuildVisible()
    }

    fun setSelected(pkgs: Set<String>) {
        selected.clear()
        selected.addAll(pkgs)
        rebuildVisible()
    }

    fun setSearch(q: String) {
        searchQuery = q.trim().lowercase()
        rebuildVisible()
    }

    fun selectedPackages(): Set<String> = selected.toSet()

    private fun rebuildVisible() {
        val filtered = if (searchQuery.isEmpty()) allItems
        else allItems.filter {
            it.label.lowercase().contains(searchQuery) ||
                it.packageName.lowercase().contains(searchQuery)
        }
        visibleItems = filtered.sortedWith(
            compareByDescending<AppItem> { it.packageName in selected }
                .thenBy { it.label.lowercase() }
        )
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_app, parent, false)
        return VH(view)
    }

    override fun getItemCount(): Int = visibleItems.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        holder.bind(visibleItems[position])
    }

    inner class VH(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val icon: ImageView = itemView.findViewById(R.id.icon)
        private val label: TextView = itemView.findViewById(R.id.label)
        private val pkg: TextView = itemView.findViewById(R.id.pkg)
        private val check: CheckBox = itemView.findViewById(R.id.check)

        fun bind(item: AppItem) {
            icon.setImageDrawable(item.icon)
            label.text = item.label
            pkg.text = item.packageName
            check.setOnCheckedChangeListener(null)
            check.isChecked = item.packageName in selected
            check.setOnCheckedChangeListener { _, isChecked ->
                if (isChecked) selected.add(item.packageName)
                else selected.remove(item.packageName)
                onSelectionChanged()
            }
            itemView.setOnClickListener { check.toggle() }
        }
    }
}
